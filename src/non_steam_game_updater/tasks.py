import logging

from non_steam_game_updater.models import ManifestConfig
from non_steam_game_updater.updaters.non_steam_updater import NonSteamUpdater

logger = logging.getLogger(__name__)


def run_update_shortcuts_task(
    manifest_configs: dict[str, ManifestConfig],
    filter_game_id: str | None = None,
    filter_platform_type: str | None = None,
    filter_source_type: str | None = None,
    steam3_id: str | None = None,
    prune: bool = False,
) -> bool:
    """Update Steam shortcuts for all configured manifest files."""
    logger.info("Running Steam shortcuts update...")
    try:
        updater = NonSteamUpdater(steam3_id=steam3_id)
        extra_kwargs = {"prune": True} if prune else {}
        updater.update_from_manifests(
            manifest_configs,
            filter_game_id=filter_game_id,
            filter_platform_type=filter_platform_type,
            filter_source_type=filter_source_type,
            **extra_kwargs,
        )
        logger.info("Steam shortcuts update complete!")
        return True
    except Exception as e:
        logger.exception("Shortcuts update process failed")
        logger.error(f"Shortcuts update failed: {e}")
        return False


def run_update_shortcut_from_dict_task(game_dict: dict, steam3_id: str | None = None) -> bool:
    """Update Steam shortcuts for a single game dict."""
    logger.info("Running direct Steam shortcut update from dict...")
    try:
        updater = NonSteamUpdater(steam3_id=steam3_id)
        updater.export_game_from_dict(game_dict)
        logger.info("Direct Steam shortcut update complete!")
        return True
    except Exception as e:
        logger.exception("Direct shortcut update failed")
        logger.error(f"Direct shortcut update failed: {e}")
        return False
