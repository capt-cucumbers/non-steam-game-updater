from dataclasses import dataclass, field
from typing import Any, NotRequired, TypedDict


def _as_str(value: Any, default: str = "") -> str:
    """Coerce value to str, falling back to default when missing."""
    return str(value) if value is not None else default


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce value to int, falling back to default when missing or invalid."""
    if value is not None:
        try:
            return int(value)
        except (ValueError, TypeError):
            pass
    return default


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce value to float, falling back to default when missing or invalid."""
    if value is not None:
        try:
            return float(value)
        except (ValueError, TypeError):
            pass
    return default


def _as_bool(value: Any, default: bool = False) -> bool:
    """Coerce value to bool, falling back to default when missing."""
    if value is not None:
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("true", "1", "yes", "on")
    return default


def _as_dict(value: Any, default: dict[str, str] | None = None) -> dict[str, str]:
    """Coerce value to dict of strings, falling back to default when missing."""
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    return {} if default is None else default


# --- Config ---


@dataclass(frozen=True)
class FileConfig:
    """Shape of config.toml — one field per documented key."""

    steam_dir: str = r"C:\Program Files (x86)\Steam"
    steam3_id: str = ""
    epic_data_dir: str = r"C:\ProgramData\Epic"
    epic_launcher_manifests_dir: str = ""
    platforms: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "FileConfig":
        """Build a FileConfig from raw TOML data, coercing values tolerantly."""
        defaults = data.get("defaults", {}) if isinstance(data.get("defaults"), dict) else {}
        return cls(
            steam_dir=_as_str(defaults.get("steam_dir"), r"C:\Program Files (x86)\Steam"),
            steam3_id=_as_str(defaults.get("steam3_id") or data.get("steam3_id")),
            epic_data_dir=_as_str(defaults.get("epic_data_dir"), r"C:\ProgramData\Epic"),
            epic_launcher_manifests_dir=_as_str(defaults.get("epic_launcher_manifests_dir")),
            platforms=_as_dict(data.get("platforms")),
            sources=_as_dict(data.get("sources")),
        )


# --- Manifests ---


class ManifestImagePaths(TypedDict, total=False):
    """Relative artwork file names in a manifest entry."""

    icon: str
    logo: str
    hero: str
    background: str
    cover: str
    screenshot: str
    box: str
    cart: str
    advertisement: str
    disc: str


class AssetSources(TypedDict, total=False):
    """Per-asset source tracking in a manifest entry's media block."""

    image_paths: dict[str, str]
    video_paths: dict[str, str]
    manual_path: str
    music_path: str


class ManifestMedia(TypedDict, total=False):
    """Media block of a manifest entry."""

    game_id: str
    game_source: str
    media_dir: str
    media_source: str
    media_id: str
    image_paths: ManifestImagePaths
    video_paths: dict[str, str]
    manual_path: str
    music_path: str
    asset_sources: AssetSources
    added_at: str
    updated_at: str


class AdditionalApp(TypedDict, total=False):
    """Additional application entry in a manifest entry."""

    app_name: str
    app_path: str
    app_arguments: str
    auto_run_before: bool
    auto_run_after: bool
    wait_for_exit: bool
    priority: int


class ManifestEntry(TypedDict):
    """A single game entry in a manifest JSON file (GameBox v2 schema)."""

    game_id: str
    global_id: NotRequired[str]
    game_source: NotRequired[str]
    platform: str
    game_name: str
    game_folder: NotRequired[str]
    game_dir: str
    game_version: NotRequired[str]
    source: NotRequired[str]
    application_path: str
    application_arguments: NotRequired[str]
    config_app_path: NotRequired[str]
    config_app_arguments: NotRequired[str]
    is_installed: bool
    is_favorite: NotRequired[bool]
    is_broken: NotRequired[bool]
    is_portable: NotRequired[bool]
    is_hidden: NotRequired[bool]
    use_dosbox: NotRequired[bool]
    dosbox_config_path: NotRequired[str]
    dosbox_version_path: NotRequired[str]
    status: NotRequired[str]
    progress: NotRequired[str]
    metadata_source: NotRequired[str]
    metadata_id: NotRequired[str]
    media_source: NotRequired[str]
    media_id: NotRequired[str]
    metadata: NotRequired[dict[str, Any]]
    media: NotRequired[ManifestMedia]
    addl_apps: NotRequired[list[AdditionalApp]]
    extras: NotRequired[dict[str, Any]]
    added_at: NotRequired[str]
    updated_at: NotRequired[str]


class ManifestConfig(TypedDict):
    """A manifest mapping entry in manifests.toml."""

    manifest_name: str
    manifest_path: str


class GameData(TypedDict):
    """Normalized game data used when adding or updating Steam shortcuts."""

    game_id: str
    game_name: str
    source_name: str
    game_dir: str
    application_path: str
    application_arguments: str
    logo_image_path: str
    cover_image_path: str
    background_image_path: str
    icon_path: str


# --- Input ---


@dataclass
class GameInput:
    """Validated game input for direct CLI mode."""

    game_id: str
    game_source: str = ""
    metadata_source: str = ""
    metadata_id: str = ""
    media_source: str = ""
    media_id: str = ""
    game_name: str | None = None
    game_dir: str | None = None
    source_name: str = "Direct"
    logo_image_path: str = ""
    cover_image_path: str = ""
    background_image_path: str = ""
    icon_path: str = ""
    application_path: str = ""
    application_arguments: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "GameInput":
        """Build a GameInput from raw dict data, requiring game_id."""
        game_source = _as_str(data.get("game_source"))
        return cls(
            game_id=_as_str(data.get("game_id")),
            game_source=game_source,
            metadata_source=_as_str(data.get("metadata_source")),
            metadata_id=_as_str(data.get("metadata_id")),
            media_source=_as_str(data.get("media_source")),
            media_id=_as_str(data.get("media_id")),
            game_name=_as_str(data.get("game_name")) or None,
            game_dir=_as_str(data.get("game_dir")) or None,
            source_name=_as_str(data.get("source_name"), game_source or "Direct"),
            logo_image_path=_as_str(data.get("logo_image_path")),
            cover_image_path=_as_str(data.get("cover_image_path")),
            background_image_path=_as_str(data.get("background_image_path")),
            icon_path=_as_str(data.get("icon_path")),
            application_path=_as_str(data.get("application_path")),
            application_arguments=_as_str(data.get("application_arguments")),
        )

    def __post_init__(self) -> None:
        """Validate required fields after coercion (missing/garbage -> empty sentinel)."""
        if not isinstance(self.game_id, str) or not self.game_id.strip():
            raise ValueError("Game input is missing required key 'game_id'.")
