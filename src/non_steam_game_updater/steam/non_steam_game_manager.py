import contextlib
import logging
import os
import shutil
import tempfile
import zlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar

from vdf import binary_dump, binary_load

from non_steam_game_updater.core.helpers import detect_steam3_id, detect_steam_dir, is_steam_running
from non_steam_game_updater.core.utils import (
    backup_file,
    convert_32bit_signature,
    normalize_dir_key,
    normalize_native_path,
    quote_path,
)

logger = logging.getLogger(__name__)


class NonSteamGameManager:
    """Manage non-Steam game shortcuts in Steam's shortcuts.vdf."""

    REQUIRED_GAME_DATA_KEYS: ClassVar[list[str]] = [
        "game_name",
        "source_name",
        "game_dir",
        "application_path",
    ]
    ARTWORK_KEYS: ClassVar[list[str]] = [
        "logo_image_path",
        "cover_image_path",
        "background_image_path",
        "icon_path",
    ]

    def __init__(
        self,
        steam_dir: str | Path | None = None,
        steam3_id: str | None = None,
        check_steam_running: bool = True,
    ) -> None:
        if check_steam_running and is_steam_running():
            raise RuntimeError("Steam is currently running. Please close Steam before modifying non-steam games.")

        self.steam_dir = str(steam_dir) if steam_dir else detect_steam_dir()
        self.steam3_id = steam3_id or detect_steam3_id(self.steam_dir)

        self.userdata_dir = (Path(self.steam_dir) / "userdata" / self.steam3_id).as_posix()
        self.steam_shortcuts_path = (Path(self.userdata_dir) / "config" / "shortcuts.vdf").as_posix()
        self.grid_dir = (Path(self.userdata_dir) / "config" / "grid").as_posix()

        self.artwork = NonSteamArtworkManager(self.grid_dir)

        self.shortcuts: dict[str, dict[str, Any]] = self.read()

    def read(self) -> dict[str, dict[str, Any]]:
        """Read current non-Steam game shortcuts from shortcuts.vdf."""
        if not Path(self.steam_shortcuts_path).exists():
            logger.warning(f"Steam shortcuts.vdf not found. Starting with empty shortcuts: {self.steam_shortcuts_path}")
            return {}

        try:
            with open(self.steam_shortcuts_path, "rb") as f:
                shortcuts_parsed_vdf = binary_load(f)
            return shortcuts_parsed_vdf.get("shortcuts", {})
        except Exception as e:
            logger.error(f"Failed to parse shortcuts.vdf. Starting with empty shortcuts: {e}.")
            return {}

    def get(self, app_id: int) -> dict[str, Any] | None:
        """Return the shortcut data for an App ID, or None if not found."""
        return next((s for s in self.shortcuts.values() if s.get("appid") == app_id), None)

    def add(self, game_data: dict[str, Any]) -> int:
        """
        Add a new non-Steam game shortcut and register any associated artwork.
        Returns:
            The signed 32-bit App ID of the added shortcut.
        """
        if not all(key in game_data for key in self.REQUIRED_GAME_DATA_KEYS):
            raise ValueError(f"Game data missing one or more required keys: {self.REQUIRED_GAME_DATA_KEYS}")

        shortcuts_data = self.shortcuts

        # Determine the next available shortcut index
        next_idx = 0
        if shortcuts_data:
            numeric_keys = [int(k) for k in shortcuts_data if str(k).isdigit()]
            next_idx = (max(numeric_keys) + 1) if numeric_keys else len(shortcuts_data)
            while str(next_idx) in shortcuts_data:
                next_idx += 1

        # Extract and normalize data
        game_name = game_data["game_name"]
        source_name = game_data["source_name"]
        game_dir = quote_path(game_data["game_dir"])
        application_path = quote_path(game_data["application_path"])

        icon = normalize_native_path(game_data.get("icon_path", ""))
        launch_options = str(game_data.get("application_arguments") or "")

        # Calculate AppID and create the new shortcut entry
        app_id = self._calc_non_steam_appid(application_path, game_name)

        new_shortcut = {
            "appid": app_id,
            "AppName": game_name,
            "exe": application_path,
            "StartDir": game_dir,
            "icon": icon,
            "ShortcutPath": "",
            "LaunchOptions": launch_options,
            "IsHidden": 0,
            "AllowDesktopConfig": 1,
            "AllowOverlay": 1,
            "OpenVR": 0,
            "Devkit": 0,
            "DevkitGameID": "",
            "DevkitOverrideAppID": 0,
            "LastPlayTime": 0,
            "FlatpakAppID": "",
            "sortas": "",
            "tags": {"0": source_name},
        }

        self.shortcuts[str(next_idx)] = new_shortcut

        # Register any app artwork to be copied to Steam's grid directory
        self._stage_artwork(app_id, game_data)

        logger.info(f"Added new shortcut for game '{game_name}' with AppID {app_id}")
        return app_id

    def update(self, app_id: int, game_data: dict[str, Any]) -> int | None:
        """
        Update an existing non-Steam game shortcut for a given App ID.
        Returns:
            The App ID if updated, None if no matching shortcut was found.
        """
        if not all(key in game_data for key in self.REQUIRED_GAME_DATA_KEYS):
            raise ValueError(f"Game data missing one or more required keys: {self.REQUIRED_GAME_DATA_KEYS}")

        # Find existing shortcut using AppID
        try:
            idx_to_update = next(idx for idx, shortcut in self.shortcuts.items() if shortcut.get("appid") == app_id)
        except StopIteration:
            logger.warning(f"Update failed: Shortcut with AppID {app_id} not found.")
            return None

        existing_shortcut = self.shortcuts[idx_to_update]

        # Extract and normalize game data
        game_name = game_data["game_name"]
        source_name = game_data["source_name"]
        game_dir = quote_path(game_data["game_dir"])
        application_path = quote_path(game_data["application_path"])

        new_app_id = self._calc_non_steam_appid(application_path, game_name)

        # Update the existing shortcut entry
        update_data: dict[str, Any] = {
            "appid": new_app_id,
            "AppName": game_name,
            "exe": application_path,
            "StartDir": game_dir,
            "LaunchOptions": str(game_data.get("application_arguments") or ""),
            "tags": {"0": source_name},
        }
        if "icon_path" in game_data:
            update_data["icon"] = normalize_native_path(game_data["icon_path"])

        existing_shortcut.update(update_data)

        # If AppID changed, clean up artwork staged/stored under the old AppID
        if new_app_id != app_id:
            logger.info(f"AppID changed from {app_id} to {new_app_id} for '{game_name}'")
            self._stage_artwork(app_id, action="delete")

        # Register any app artwork to be copied to Steam's grid directory
        self._stage_artwork(new_app_id, game_data)

        logger.info(f"Updated shortcut for game '{game_name}' with AppID {new_app_id}")
        return new_app_id

    def remove(self, app_id: int) -> bool:
        """Remove a non-Steam game shortcut and mark any artwork for deletion."""
        try:
            idx_to_remove = next(idx for idx, shortcut in self.shortcuts.items() if shortcut.get("appid") == app_id)
        except StopIteration:
            return False

        del self.shortcuts[idx_to_remove]
        self._reindex_shortcuts()

        # Register any app artwork for deletion
        self._stage_artwork(app_id, action="delete")

        return True

    def save(self, update_artwork: bool = False) -> None:
        """Save the current shortcuts atomically to shortcuts.vdf, optionally committing artwork."""
        target_path = Path(self.steam_shortcuts_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        backup_file(self.steam_shortcuts_path)

        if update_artwork:
            copied_icons = self.artwork.commit()
            if copied_icons:
                self._apply_local_icon_paths(copied_icons)

        tmp_path: Path | None = None
        try:
            vdf_structure = {"shortcuts": self.shortcuts}
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target_path.parent,
                prefix=f".{target_path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)
                binary_dump(vdf_structure, tmp)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp_path, target_path)
            logger.info(f"Successfully saved shortcuts data: {self.steam_shortcuts_path}")
        except Exception as e:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            logger.error(f"Failed to save shortcuts.vdf: {e}")

    def _apply_local_icon_paths(self, copied_icons: dict[int, str]) -> None:
        """Update shortcut 'icon' fields to point at locally cached artwork icons."""
        for shortcut in self.shortcuts.values():
            app_id = shortcut.get("appid")
            if not isinstance(app_id, int):
                continue
            unsigned_id = self.convert_32bit_appid(app_id, output="unsigned")
            if isinstance(unsigned_id, int) and unsigned_id in copied_icons:
                shortcut["icon"] = copied_icons[unsigned_id]

    def find_shortcuts_by_game_dir(self, game_dir: str | Path | None) -> list[int]:
        """Return the App IDs of shortcuts whose StartDir matches the given game directory."""
        search_key = normalize_dir_key(game_dir)
        if not search_key:
            return []

        return [
            shortcut["appid"]
            for shortcut in self.shortcuts.values()
            if normalize_dir_key(shortcut.get("StartDir")) == search_key
        ]

    def prune_shortcuts_by_source(self, source_name: str, keep_game_dirs: Iterable[str | Path]) -> list[int]:
        """Remove shortcuts tagged with source_name whose StartDir is not in keep_game_dirs."""
        target_source = source_name.strip().lower()
        if not target_source:
            return []

        keep_keys = {key for game_dir in keep_game_dirs if (key := normalize_dir_key(game_dir))}
        to_remove: list[int] = []
        for shortcut in self.shortcuts.values():
            tags = shortcut.get("tags")
            if not isinstance(tags, dict):
                continue
            has_source_tag = any(str(tag).strip().lower() == target_source for tag in tags.values())
            if not has_source_tag:
                continue
            start_key = normalize_dir_key(shortcut.get("StartDir"))
            if not start_key or start_key not in keep_keys:
                app_id = shortcut.get("appid")
                if isinstance(app_id, int):
                    to_remove.append(app_id)

        for app_id in to_remove:
            self.remove(app_id)
        return to_remove

    def convert_32bit_appid(self, appid_data: int | list[int], output: str = "signed") -> int | list[int]:
        """
        Convert 32-bit App ID(s) between signed and unsigned formats.
        Returns:
            A single converted int, or a list of converted ints for batch input.
        """
        if isinstance(appid_data, list):
            return [convert_32bit_signature(appid, output=output) for appid in appid_data]

        return convert_32bit_signature(appid_data, output=output)

    def _calc_non_steam_appid(self, exe_path: str, app_name: str) -> int:
        """Calculate the signed 32-bit App ID used for a non-Steam game shortcut."""
        key = (exe_path + app_name).encode("utf-8")
        crc_value = zlib.crc32(key) & 0xFFFFFFFF
        unsigned_app_id = crc_value | 0x80000000
        return convert_32bit_signature(unsigned_app_id)

    def _reindex_shortcuts(self) -> None:
        """Re-index the shortcut dictionary keys sequentially from '0' to N-1."""
        self.shortcuts = {str(i): s for i, s in enumerate(self.shortcuts.values())}

    def _stage_artwork(self, app_id: int, game_data: dict[str, Any] | None = None, action: str = "save") -> None:
        """Stage artwork files for save or delete, keyed by the unsigned App ID."""
        if action == "save" and game_data:
            artwork_data = {k: game_data[k] for k in self.ARTWORK_KEYS if k in game_data}
            if artwork_data:
                unsigned_id = self.convert_32bit_appid(app_id, output="unsigned")
                self.artwork.stage_save(unsigned_id, artwork_data)
        elif action == "delete":
            unsigned_id = self.convert_32bit_appid(app_id, output="unsigned")
            self.artwork.stage_delete(unsigned_id)

    def __enter__(self) -> "NonSteamGameManager":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is None:
            self.save()


class NonSteamArtworkManager:
    """Handle Steam grid artwork for non-Steam games."""

    ARTWORK_TYPES: ClassVar[dict[str, tuple[str, str]]] = {
        "logo_image_path": ("_logo", ".png"),
        "cover_image_path": ("p", ".jpg"),
        "background_image_path": ("_hero", ".jpg"),
        "icon_path": ("_icon", ".png"),
    }
    NON_COPYABLE_ICON_SUFFIXES: ClassVar[set[str]] = {".exe", ".dll"}

    def __init__(self, grid_dir: str | Path) -> None:
        self.grid_dir = str(grid_dir)
        self.pending: dict[int, dict[str, Any]] = {}

    def stage_save(self, app_id: int, artwork_data: dict[str, Any]) -> None:
        """Stage artwork to be copied on the next commit."""
        self.pending[app_id] = {"action": "write", "data": artwork_data}

    def stage_delete(self, app_id: int) -> None:
        """Stage artwork to be deleted on the next commit."""
        self.pending[app_id] = {"action": "delete"}

    def commit(self) -> dict[int, str]:
        """Execute all pending artwork operations and return locally cached icon paths by unsigned App ID."""
        if not self.pending:
            return {}

        Path(self.grid_dir).mkdir(parents=True, exist_ok=True)
        copied_icons: dict[int, str] = {}

        for app_id, operation in self.pending.items():
            if operation["action"] == "write":
                local_icon = self._save_artwork(app_id, operation["data"])
                if local_icon:
                    copied_icons[app_id] = local_icon
            elif operation["action"] == "delete":
                self._delete_artwork(app_id)

        self.pending.clear()
        return copied_icons

    def _save_artwork(self, app_id: int, artwork_data: dict[str, Any]) -> str | None:
        """Copy artwork files for a game into the Steam grid directory, returning local icon path if cached."""
        local_icon_path: str | None = None

        for key, (suffix, default_ext) in self.ARTWORK_TYPES.items():
            raw_src = artwork_data.get(key)
            if not raw_src:
                if key == "icon_path" and "icon_path" in artwork_data:
                    self._delete_artwork_suffix(app_id, suffix)
                continue

            src = Path(normalize_native_path(raw_src))
            if key == "icon_path" and src.suffix.lower() in self.NON_COPYABLE_ICON_SUFFIXES:
                self._delete_artwork_suffix(app_id, suffix)
                continue

            if not src.exists():
                logger.warning(f"Artwork not found: {raw_src}")
                continue

            ext = src.suffix or default_ext
            dest = Path(self.grid_dir) / f"{app_id}{suffix}{ext}"

            same_file = False
            if dest.exists():
                with contextlib.suppress(OSError):
                    same_file = src.resolve() == dest.resolve()

            try:
                if not same_file:
                    shutil.copy2(str(src), dest)
                    logger.info(f"Copied artwork: {dest.name}")
                if key == "icon_path":
                    self._delete_artwork_suffix(app_id, suffix, exclude_name=dest.name)
                    local_icon_path = normalize_native_path(dest)
            except Exception as e:
                logger.error(f"Failed to copy artwork: {e}")

        return local_icon_path

    def _delete_artwork_suffix(self, app_id: int, suffix: str, *, exclude_name: str | None = None) -> None:
        """Delete artwork files matching an App ID and suffix inside grid_dir."""
        grid_path = Path(self.grid_dir)
        if not grid_path.exists():
            return
        for file_path in grid_path.glob(f"{app_id}{suffix}.*"):
            if exclude_name and file_path.name == exclude_name:
                continue
            try:
                file_path.unlink(missing_ok=True)
                logger.debug(f"Deleted artwork: {file_path}")
            except OSError as e:
                logger.error(f"Failed to delete artwork: {e}")

    def _delete_artwork(self, app_id: int) -> None:
        """Delete all artwork files for an App ID."""
        for suffix, _ in self.ARTWORK_TYPES.values():
            self._delete_artwork_suffix(app_id, suffix)
