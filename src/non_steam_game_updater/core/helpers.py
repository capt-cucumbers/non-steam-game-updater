import json
import logging
import re
import subprocess
from pathlib import Path

from non_steam_game_updater.core import config

logger = logging.getLogger(__name__)


# --- Platform ---


def get_platform_name(platform_type: str) -> str | None:
    """Return the display name for a platform type (e.g. 'windows' -> 'Windows')."""
    return config.settings.platform_names.get(platform_type)


def get_platform_type(platform_name: str) -> str | None:
    """Return the platform type for a display name (e.g. 'Windows' -> 'windows')."""
    for p_type, p_name in config.settings.platform_names.items():
        if p_name.lower() == platform_name.lower():
            return p_type
    return None


# --- Source ---


def get_source_name(source_type: str) -> str | None:
    """Return the display name for a source type (e.g. 'custom' -> 'Custom')."""
    return config.settings.source_names.get(source_type)


def get_source_type(source_name: str) -> str | None:
    """Return the source type for a display name (e.g. 'Custom' -> 'custom')."""
    for s_type, s_name in config.settings.source_names.items():
        if s_name.lower() == source_name.lower():
            return s_type
    return None


# --- Epic ---


def get_epic_app_name_from_uri(app_uri: str) -> str | None:
    """Extract the Epic AppName from a launcher URI, e.g. 'com.epicgames.launcher://apps/<id>?...'."""
    if not (match := re.search(r"apps/([a-fA-F0-9]+)\?", app_uri)):
        if "com.epicgames.launcher://" in app_uri or "apps/" in app_uri:
            logger.warning(f"Could not extract Epic AppName from URI: {app_uri}")
        return None

    return match.group(1).lower()


def get_epic_game_details_from_app_name(app_name: str) -> tuple[str | None, str | None]:
    """Scan Epic manifests for an AppName and return its install location and launch executable."""
    manifests_dir = config.settings.epic_launcher_manifests_dir
    if not manifests_dir.exists():
        logger.warning(f"Epic Manifests directory not found at: {manifests_dir}")
        return None, None

    for item_path in manifests_dir.glob("*.item"):
        try:
            with item_path.open("r", encoding="utf-8") as f:
                manifest_data = json.load(f)

            if manifest_data.get("AppName", "").lower() == app_name.lower():
                return manifest_data.get("InstallLocation"), manifest_data.get("LaunchExecutable")

        except json.JSONDecodeError:
            logger.warning(f"Skipping corrupt manifest file: {item_path}")
        except Exception as e:
            logger.error(f"Error reading manifest {item_path}: {e}")

    logger.warning(f"No installed manifest found for Epic AppName: {app_name}")
    return None, None


# --- Steam Detection ---


def detect_steam_dir() -> str:
    """Detect the Steam installation path, raising FileNotFoundError if not found."""
    steam_dirs = [
        r"C:\Program Files (x86)\Steam",
        r"C:\Program Files\Steam",
    ]
    for steam_dir in steam_dirs:
        userdata_root_dir = Path(steam_dir) / "userdata"
        if Path(steam_dir).exists() and userdata_root_dir.exists():
            return steam_dir

    raise FileNotFoundError("Could not auto-detect Steam path. Please provide it manually.")


def detect_steam3_id(steam_dir: str | Path) -> str:
    """Detect the Steam3 ID (first userdata folder), raising FileNotFoundError if not found."""
    userdata_root_dir = Path(steam_dir) / "userdata"
    if not userdata_root_dir.exists():
        raise FileNotFoundError(f"Steam userdata directory not found: {userdata_root_dir}")

    candidates = sorted(
        (folder.name for folder in userdata_root_dir.iterdir() if folder.name.isdigit() and folder.is_dir()),
        key=int,
    )
    if candidates:
        return candidates[0]

    raise FileNotFoundError("Could not auto-detect Steam3 ID. Please provide it manually.")


def is_steam_running() -> bool:
    """Check whether a steam.exe process is currently running."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        return "steam.exe" in result.stdout.lower()
    except Exception as e:
        logger.error(f"Error: Could not check for Steam processes: {e}")
        return False
