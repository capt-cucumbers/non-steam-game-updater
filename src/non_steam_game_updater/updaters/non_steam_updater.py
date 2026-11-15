import logging
from pathlib import Path
from typing import Any

from non_steam_game_updater.core import config
from non_steam_game_updater.core.helpers import (
    get_epic_app_name_from_uri,
    get_epic_game_details_from_app_name,
    get_platform_name,
    get_platform_type,
    get_source_name,
    get_source_type,
)
from non_steam_game_updater.core.utils import join_native_path, normalize_native_path, read_json
from non_steam_game_updater.models import GameData, ManifestConfig
from non_steam_game_updater.steam.non_steam_game_manager import NonSteamGameManager
from non_steam_game_updater.steam.steam_collections_manager import SteamCollectionsManager

logger = logging.getLogger(__name__)


def _is_uri_or_absolute(path_value: str) -> bool:
    """Return True if path_value is absolute, a UNC path, or a URL/URI scheme."""
    return Path(path_value).is_absolute() or ":" in path_value or "://" in path_value or path_value.startswith("\\\\")


class NonSteamUpdater:
    """
    Manage non-Steam games by creating shortcuts and collections in Steam
    from manifest files or single game dicts.
    """

    NON_STEAM_GAME_APP_NAME: str = "Play on Steam"

    def __init__(
        self,
        steam3_id: str | None = None,
        steam_dir: str | Path | None = None,
        check_steam_running: bool = True,
    ) -> None:
        target_steam3_id = steam3_id or config.settings.steam3_id or None
        self.nsgm = NonSteamGameManager(
            steam3_id=target_steam3_id,
            steam_dir=steam_dir or config.settings.steam_dir,
            check_steam_running=check_steam_running,
        )
        self.scm = SteamCollectionsManager(
            steam3_id=target_steam3_id,
            steam_dir=steam_dir or config.settings.steam_dir,
            check_steam_running=check_steam_running,
        )

    def update_from_manifests(
        self,
        manifest_configs: dict[str, ManifestConfig],
        filter_game_id: str | None = None,
        filter_platform_type: str | None = None,
        filter_source_type: str | None = None,
        prune: bool = False,
    ) -> None:
        """Update shortcuts for all configured manifest files."""
        for manifest_key, manifest_config in manifest_configs.items():
            self.update_from_manifest(
                manifest_key,
                manifest_config,
                filter_game_id=filter_game_id,
                filter_platform_type=filter_platform_type,
                filter_source_type=filter_source_type,
                prune=prune,
            )

    def update_from_manifest(
        self,
        manifest_key: str,
        manifest_config: ManifestConfig,
        filter_game_id: str | None = None,
        filter_platform_type: str | None = None,
        filter_source_type: str | None = None,
        prune: bool = False,
    ) -> None:
        """Update shortcuts for a single manifest config file."""
        manifest_path = manifest_config.get("manifest_path")
        if not manifest_path or not Path(manifest_path).exists():
            logger.error(f"Manifest file not found: {manifest_path}")
            return

        manifest_data = read_json(manifest_path) or {}
        if not manifest_data:
            logger.error(f"Manifest file is empty: {manifest_path}")
            return

        target_platform_type = self._normalize_platform_type(filter_platform_type)
        target_source_type = self._normalize_source_type(filter_source_type)

        games_list = []
        for entry_id, manifest_entry in manifest_data.items():
            game_id = str(manifest_entry.get("game_id") or entry_id)
            game_data = self._parse_manifest_entry(
                game_id,
                manifest_entry,
                filter_game_id=filter_game_id,
                target_platform_type=target_platform_type,
                target_source_type=target_source_type,
            )
            if game_data:
                games_list.append(game_data)

        can_prune = prune and not (filter_game_id or filter_platform_type or filter_source_type)
        total_games = len(games_list)
        if not total_games and not can_prune:
            logger.info(f"No games to export from manifest config: {manifest_key}")
            return

        successful_pairs: list[tuple[GameData, int]] = []
        for i, game_data in enumerate(games_list, 1):
            logger.info(f"[{i}/{total_games}] Processing game '{game_data['game_name']}'...")
            appid = self._update_steam_shortcut(game_data["game_dir"], game_data)
            if appid is not None:
                successful_pairs.append((game_data, appid))

        pruned_by_source: dict[str, list[int]] = {}
        if can_prune:
            pruned_by_source = self._prune_manifest_orphans(manifest_key, games_list)

        # Save Steam shortcuts and update collections only when shortcuts were applied or pruned
        if successful_pairs or pruned_by_source:
            self.nsgm.save(update_artwork=True)

            source_groups: dict[str, list[int]] = {}
            for g_data, signed_id in successful_pairs:
                unsigned_id = self.nsgm.convert_32bit_appid(signed_id, output="unsigned")
                if isinstance(unsigned_id, int):
                    source_groups.setdefault(g_data["source_name"], []).append(unsigned_id)

            for s_name, s_app_ids in source_groups.items():
                self._update_steam_collection(s_name, s_app_ids)

            for s_name, removed_signed_ids in pruned_by_source.items():
                if s_name in source_groups:
                    continue
                if collection_id := self.scm.find_collection_by_name(s_name):
                    existing_col = self.scm.get(collection_id) or {}
                    removed_unsigned = self.nsgm.convert_32bit_appid(removed_signed_ids, output="unsigned")
                    if isinstance(removed_unsigned, list) and removed_unsigned:
                        removed_set = set(removed_unsigned)
                        remaining_added = [aid for aid in existing_col.get("added", []) if aid not in removed_set]
                        col_name = existing_col.get("name") or s_name
                        self.scm.update(collection_id, col_name, added=remaining_added, merge=False)

            self.scm.save()

    def _prune_manifest_orphans(self, manifest_key: str, games_list: list[GameData]) -> dict[str, list[int]]:
        """Prune Steam shortcuts belonging to a manifest's source(s) whose game_dir is no longer active."""
        active_by_source: dict[str, list[str]] = {}
        for game_data in games_list:
            active_by_source.setdefault(game_data["source_name"], []).append(game_data["game_dir"])

        if not active_by_source and "." in manifest_key:
            source_key = manifest_key.split(".", 1)[1]
            inferred_source = get_source_name(source_key) or source_key
            active_by_source[inferred_source] = []

        pruned_by_source: dict[str, list[int]] = {}
        for s_name, keep_dirs in active_by_source.items():
            if removed_ids := self.nsgm.prune_shortcuts_by_source(s_name, keep_dirs):
                pruned_by_source[s_name] = removed_ids
        return pruned_by_source

    @staticmethod
    def _resolve_source_name(entry: dict[str, Any], *, default: str) -> str:
        """Resolve Steam collection display name from explicit fields or canonical game_source."""
        game_source = str(entry.get("game_source") or "").strip()
        explicit = entry.get("source_name") or entry.get("source")
        if explicit:
            cleaned = str(explicit).strip()
            if cleaned:
                if game_source and cleaned.lower() == game_source.lower():
                    return get_source_name(game_source) or cleaned
                return cleaned
        if game_source:
            return get_source_name(game_source) or game_source
        return default

    def export_game_from_dict(self, game_dict: dict[str, Any]) -> None:
        """Export a single game dict directly to Steam."""
        game_id = game_dict.get("game_id")
        game_id_str = str(game_id or "")
        game_name = str(game_dict.get("game_name") or game_id_str)
        game_dir = str(game_dict.get("game_dir") or "")
        raw_app_path = str(game_dict.get("application_path") or "")
        game_dir_resolved, application_abs_path = self._resolve_launch_paths(raw_app_path, game_dir)
        source_name = self._resolve_source_name(game_dict, default="Direct")

        game_data: GameData = {
            "game_id": game_id_str,
            "game_name": game_name,
            "source_name": source_name,
            "game_dir": game_dir_resolved,
            "application_path": application_abs_path,
            "application_arguments": game_dict.get("application_arguments") or "",
            "logo_image_path": normalize_native_path(game_dict.get("logo_image_path") or ""),
            "cover_image_path": normalize_native_path(game_dict.get("cover_image_path") or ""),
            "background_image_path": normalize_native_path(game_dict.get("background_image_path") or ""),
            "icon_path": normalize_native_path(game_dict.get("icon_path") or ""),
        }

        logger.info(f"Processing direct game '{game_name}'...")
        appid = self._update_steam_shortcut(game_dir_resolved, game_data)

        # Save Steam shortcuts
        self.nsgm.save(update_artwork=True)

        # Update collections
        if appid:
            unsigned_ids = self.nsgm.convert_32bit_appid([appid], output="unsigned")
            if isinstance(unsigned_ids, list):
                self._update_steam_collection(source_name, unsigned_ids, merge=True)

        self.scm.save()

    # --- Private Helpers ---

    def _parse_manifest_entry(
        self,
        game_id: str,
        manifest_entry: dict[str, Any],
        filter_game_id: str | None = None,
        target_platform_type: str | None = None,
        target_source_type: str | None = None,
    ) -> GameData | None:
        """Parse and validate a single manifest entry into normalized game data."""
        if filter_game_id and game_id != filter_game_id:
            return None

        source_name = manifest_entry.get("source")
        game_source = str(manifest_entry.get("game_source") or "").strip()
        if not game_source and source_name:
            game_source = get_source_type(source_name) or source_name
        if target_source_type and game_source and game_source.lower() != target_source_type.lower():
            return None

        platform_name = manifest_entry.get("platform")
        if not platform_name:
            return None

        platform_type = get_platform_type(platform_name)
        if not platform_type or (target_platform_type and platform_type.lower() != target_platform_type.lower()):
            return None

        if not manifest_entry.get("is_installed", False):
            return None

        game_name = manifest_entry.get("game_name")
        game_dir = manifest_entry.get("game_dir")
        if not game_name or not game_dir:
            return None

        app_path = manifest_entry.get("application_path")
        game_dir_resolved, application_abs_path = self._resolve_launch_paths(app_path, str(game_dir))

        if not application_abs_path:
            logger.warning(f"No application path found in manifest for '{game_name}'. Skipping.")
            return None

        raw_media = manifest_entry.get("media")
        media = raw_media if isinstance(raw_media, dict) else {}
        raw_metadata = manifest_entry.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        media_dir = media.get("media_dir") or metadata.get("metadata_dir")
        raw_image_paths = media.get("image_paths")
        image_paths = raw_image_paths if isinstance(raw_image_paths, dict) else {}

        def resolve_image(*keys: str) -> str:
            for k in keys:
                if path := self._resolve_image_path(image_paths, media_dir, game_dir_resolved, k):
                    return path
            return ""

        return {
            "game_id": game_id,
            "game_name": game_name,
            "source_name": self._resolve_source_name(manifest_entry, default="Local"),
            "game_dir": game_dir_resolved,
            "application_path": application_abs_path,
            "application_arguments": manifest_entry.get("application_arguments") or "",
            "logo_image_path": resolve_image("logo", "Logo"),
            "cover_image_path": resolve_image("cover", "Cover", "grid"),
            "background_image_path": resolve_image("hero", "Hero", "background", "Background"),
            "icon_path": resolve_image("icon", "Icon"),
        }

    def _resolve_launch_paths(self, app_path: str | None, game_dir: str) -> tuple[str, str]:
        """Resolve Epic launcher URIs and join relative executables preserving Windows separators."""
        game_dir_resolved = str(game_dir)
        resolved_app_path = str(app_path or "")

        if resolved_app_path and "com.epicgames.launcher://" in resolved_app_path:
            game_dir_resolved, resolved_app_path = self._resolve_epic_launcher_paths(
                resolved_app_path, game_dir_resolved
            )

        if not resolved_app_path:
            return game_dir_resolved, ""

        if _is_uri_or_absolute(resolved_app_path) or not game_dir_resolved:
            return game_dir_resolved, resolved_app_path

        return game_dir_resolved, join_native_path(game_dir_resolved, resolved_app_path)

    @staticmethod
    def _resolve_epic_launcher_paths(app_path: str, game_dir: str) -> tuple[str, str]:
        """Resolve game directory and executable path for Epic Games launcher URIs."""
        app_name_epic = get_epic_app_name_from_uri(app_path)
        if app_name_epic:
            epic_game_dir, epic_app_path = get_epic_game_details_from_app_name(app_name_epic)
            if epic_game_dir and epic_app_path:
                return epic_game_dir, epic_app_path
        return game_dir, app_path

    @staticmethod
    def _resolve_image_path(image_paths: dict[str, Any], media_dir: str | None, game_dir: str, img_key: str) -> str:
        """Resolve an image path relative to the media dir or game dir preserving native path format."""
        rel_path = image_paths.get(img_key)
        if not rel_path:
            return ""
        rel_str = str(rel_path).strip()
        if _is_uri_or_absolute(rel_str):
            return normalize_native_path(rel_str)
        for base_dir in (media_dir, game_dir):
            if not base_dir:
                continue
            resolved = join_native_path(str(base_dir), rel_str)
            if Path(resolved).exists():
                return resolved
        return ""

    @staticmethod
    def _normalize_platform_type(filter_platform_type: str | None) -> str | None:
        """Return the platform type for a filter, accepting either a type or a display name."""
        if not filter_platform_type:
            return None
        if get_platform_name(filter_platform_type):
            return filter_platform_type
        return get_platform_type(filter_platform_type) or filter_platform_type

    @staticmethod
    def _normalize_source_type(filter_source_type: str | None) -> str | None:
        """Return the source type for a filter, accepting either a type or a display name."""
        if not filter_source_type:
            return None
        if get_source_name(filter_source_type):
            return filter_source_type
        return get_source_type(filter_source_type) or filter_source_type

    def _update_steam_shortcut(self, game_dir: str, game_data: dict[str, Any]) -> int | None:
        """Add or update the Steam shortcut for a game directory, returning the App ID."""
        if app_ids := self.nsgm.find_shortcuts_by_game_dir(game_dir):
            app_id = self.nsgm.update(app_ids[0], game_data)
        else:
            app_id = self.nsgm.add(game_data)
        return app_id

    def _update_steam_collection(self, collection_name: str, app_ids: list[int], merge: bool = False) -> str:
        """Add or update the Steam collection for a source name, returning its collection ID."""
        if collection_id := self.scm.find_collection_by_name(collection_name):
            self.scm.update(collection_id, collection_name, added=app_ids, merge=merge)
        else:
            collection_id = self.scm.create_scm_collection_id(collection_name)
            self.scm.update(collection_id, collection_name, added=app_ids, merge=merge)
        return collection_id
