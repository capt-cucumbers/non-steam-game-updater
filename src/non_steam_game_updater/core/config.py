import logging
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from non_steam_game_updater.core.utils import read_toml
from non_steam_game_updater.models import FileConfig

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_DIR = Path(__file__).resolve().parents[1]

env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    load_dotenv(env_file)


def _load_file_config() -> FileConfig:
    """Read config.toml and coerce its contents into a FileConfig model."""
    data = read_toml(PROJECT_ROOT / "config.toml") or {}
    if not isinstance(data, dict):
        logger.warning("config.toml did not contain a table; using defaults.")
        data = {}

    known = {f.name for f in fields(FileConfig)} | {"defaults"}
    for key in data:
        if key not in known:
            logger.warning(f"Ignoring unknown config.toml key '{key}'.")

    return FileConfig.from_dict(data)


@dataclass(frozen=True)
class Settings:
    """All runtime configuration settings, loaded from environment and config.toml."""

    # Credentials
    steam3_id: str
    # Paths
    steam_dir: Path
    epic_data_dir: Path
    epic_launcher_manifests_dir: Path
    # Maps
    platform_names: dict[str, str]
    source_names: dict[str, str]

    @classmethod
    def load(cls, file: FileConfig) -> "Settings":
        """Build runtime settings: environment wins, then config.toml, then defaults."""
        epic_data_dir = Path(file.epic_data_dir)
        epic_launcher_manifests_dir = (
            Path(file.epic_launcher_manifests_dir)
            if file.epic_launcher_manifests_dir
            else epic_data_dir / "EpicGamesLauncher" / "Data" / "Manifests"
        )
        return cls(
            steam3_id=os.getenv("STEAM3_ID") or file.steam3_id,
            steam_dir=Path(file.steam_dir),
            epic_data_dir=epic_data_dir,
            epic_launcher_manifests_dir=epic_launcher_manifests_dir,
            platform_names=file.platforms,
            source_names=file.sources,
        )


settings = Settings.load(_load_file_config())


# --- Manifest Map ---


def _flatten_manifests(data: dict, prefix: str = "") -> dict[str, dict[str, Any]]:
    """Flatten nested manifests.toml tables into {key: manifest_config} entries."""
    flat: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        full_key = f"{prefix}{key}"
        if isinstance(value, dict):
            if "manifest_path" in value:
                flat[full_key] = value
            else:
                flat.update(_flatten_manifests(value, prefix=f"{full_key}."))
    return flat


MANIFESTS_TOML_PATH = PROJECT_ROOT / "manifests.toml"
MANIFEST_PATHS: dict[str, dict[str, Any]] = _flatten_manifests(read_toml(MANIFESTS_TOML_PATH) or {})

MANIFEST_NAMES: dict[str, str] = {
    m_type: m_info.get("manifest_name", m_type) for m_type, m_info in MANIFEST_PATHS.items()
}
