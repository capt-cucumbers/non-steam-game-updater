import logging
from pathlib import Path

from non_steam_game_updater.core import config
from non_steam_game_updater.core.utils import convert_32bit_signature

logger = logging.getLogger(__name__)

try:
    from vdf import binary_load
except ImportError:
    binary_load = None
    logger.warning("vdf.binary_load not found. Steam shortcuts parsing will be disabled.")


class SteamShortcutManager:
    """Build a lookup of Steam play action URIs keyed by game installation directory."""

    PLAY_ACTION_TEMPLATE: str = "steam://rungameid/{app_id_64}"

    def __init__(self, shortcuts_path: str | Path | None = None) -> None:
        self.shortcuts_path = Path(
            shortcuts_path
            or config.settings.steam_dir / "userdata" / config.settings.steam3_id / "config" / "shortcuts.vdf"
        )
        self.play_action_map: dict[str, str] = {}

        shortcuts_data = self._load_shortcuts_data()
        self._build_lookup(shortcuts_data)

    def get_play_action(self, game_dir: str) -> str | None:
        """Return the play action URI for a game directory, or None if not found."""
        if not game_dir:
            return None

        clean_dir = str(game_dir).strip().strip('"')
        if not clean_dir:
            return None
        norm_dir = Path(clean_dir).as_posix().rstrip("/").lower()
        return self.play_action_map.get(norm_dir)

    def _load_shortcuts_data(self) -> dict | None:
        """Read the binary VDF file and return the raw shortcut data."""
        if not self.shortcuts_path.exists():
            logger.error(f"Steam shortcuts.vdf not found: {self.shortcuts_path}")
            return None

        try:
            with open(self.shortcuts_path, "rb") as f:
                if binary_load:
                    data = binary_load(f)
                    return data.get("shortcuts", {})
                logger.warning("Steam shortcuts parsing skipped (binary_load missing).")
                return {}
        except Exception as e:
            logger.error(f"Failed to parse shortcuts.vdf: {e}")
            return None

    def _build_lookup(self, shortcuts_data: dict | None) -> None:
        """Index play action URIs from raw shortcut data by normalized StartDir."""
        if not shortcuts_data:
            logger.warning("No shortcut data provided to build_lookup.")
            return

        count = 0
        for shortcut in shortcuts_data.values():
            start_dir = shortcut.get("StartDir")
            app_id = shortcut.get("appid")

            if start_dir and app_id:
                clean_dir = str(start_dir).strip().strip('"')
                if not clean_dir:
                    continue
                norm_dir = Path(clean_dir).as_posix().rstrip("/").lower()

                try:
                    app_id_32 = convert_32bit_signature(app_id, output="unsigned")
                    app_id_64 = (app_id_32 << 32) | 0x02000000
                    play_action = self.PLAY_ACTION_TEMPLATE.replace("{app_id_64}", str(app_id_64))
                    self.play_action_map[norm_dir] = play_action
                    count += 1
                except Exception as e:
                    logger.debug(f"Error calculating URI for {start_dir}: {e}")

        logger.info(f"Lookup build complete. Indexed {count} non-Steam games.")
