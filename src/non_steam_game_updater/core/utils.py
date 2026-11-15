import contextlib
import json
import logging
import ntpath
import os
import shutil
import struct
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# --- Platform Setup ---


def enable_ansi_utf8() -> None:
    """Enable ANSI escape sequences and UTF-8 output on Windows consoles."""
    if sys.platform != "win32":
        return
    os.system("")
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


# --- File I/O ---


def read_toml(path: str | Path | None, default: Any = None) -> Any:
    """Load data from a TOML file with specified fallback."""
    fallback = {} if default is None else default
    if not path:
        return fallback

    p = Path(path)
    if not p.exists():
        return fallback

    try:
        with p.open("rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logger.error(f"Failed to read TOML from {path}: {e}")

    return fallback


def read_json(path: str | Path | None, default: Any = None) -> Any:
    """Load data from a JSON file with specified fallback."""
    fallback = {} if default is None else default
    if not path:
        return fallback

    p = Path(path)
    if not p.exists():
        return fallback

    try:
        with p.open("r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read JSON from {path}: {e}")

    return fallback


def write_json(path: str | Path | None, data: Any, indent: int = 4) -> bool:
    """Save data atomically to a JSON file using temp-file + fsync + os.replace."""
    if not path:
        return False
    p = Path(path)
    tmp_path: Path | None = None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=p.parent,
            prefix=f".{p.stem}.",
            suffix=".tmp",
            encoding="utf-8",
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
            json.dump(data, tmp, indent=indent, ensure_ascii=False)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_path, p)
        return True
    except Exception as e:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        logger.error(f"Failed to write JSON to {path}: {e}")
        return False


def backup_file(path: str | Path | None) -> bool:
    """Create a .bak redundancy copy of a file if it exists."""
    if not path:
        return False

    p = Path(path)
    if not p.exists():
        return False

    try:
        backup_p = p.with_suffix(p.suffix + ".bak")
        shutil.copyfile(p, backup_p)
        logger.info(f"Successfully created backup: {backup_p}")
        return True
    except Exception as e:
        logger.error(f"Failed to backup file {path}: {e}")

    return False


# --- Paths ---


def _is_windows_style_path(path_str: str) -> bool:
    """Return True if path_str looks like a Windows drive/UNC path or we are on Windows."""
    if not path_str or "://" in path_str:
        return False
    is_drive = len(path_str) >= 2 and path_str[0].isalpha() and path_str[1] == ":"
    is_fwd_unc = len(path_str) > 2 and path_str[0] == "/" and path_str[1] == "/" and path_str[2] != "/"
    return sys.platform == "win32" or "\\" in path_str or is_drive or is_fwd_unc


def normalize_native_path(path: str | Path | None) -> str:
    """Normalize a path while preserving Windows backslashes for drive and UNC paths."""
    if not path:
        return ""
    raw = str(path).strip()
    if not raw or "://" in raw:
        return raw
    if _is_windows_style_path(raw):
        return ntpath.normpath(raw.replace("/", "\\"))
    return str(Path(raw))


def join_native_path(base_dir: str | Path, rel_path: str | Path) -> str:
    """Join a relative path to base_dir preserving Windows backslashes for Windows roots."""
    base_str = str(base_dir).strip()
    rel_str = str(rel_path).strip()
    if _is_windows_style_path(base_str):
        return ntpath.normpath(ntpath.join(base_str.replace("/", "\\"), rel_str.replace("/", "\\")))
    return str(Path(base_str) / rel_str)


def normalize_dir_key(path: str | Path | None) -> str:
    """Return a canonical lowercase forward-slash comparison key for a game directory."""
    if not path:
        return ""
    cleaned = str(path).strip().strip('"')
    if not cleaned:
        return ""
    return cleaned.replace("\\", "/").rstrip("/").lower()


def quote_path(path: str | Path | None) -> str:
    """Ensure a file or directory path is wrapped in double quotes."""
    if not path:
        return ""
    clean = str(path).strip().strip('"')
    return f'"{clean}"' if clean else ""


# --- Data ---


def convert_32bit_signature(val: int, output: str = "signed") -> int:
    """Convert a 32-bit integer between signed and unsigned representations."""
    if output == "signed":
        return struct.unpack("<i", struct.pack("<I", val))[0]
    if output == "unsigned":
        return struct.unpack("<I", struct.pack("<i", val))[0]
    raise ValueError("Invalid output mode. Must be 'signed' or 'unsigned'.")
