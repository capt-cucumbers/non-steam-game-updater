# Non-Steam Game Updater

[![CI](https://github.com/capt-cucumbers/non-steam-game-updater/actions/workflows/ci.yml/badge.svg)](https://github.com/capt-cucumbers/non-steam-game-updater/actions/workflows/ci.yml)
[![Python 3.11-3.13](https://img.shields.io/badge/python-3.11--3.13-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)](https://www.microsoft.com/windows)

Adds and updates Steam non-Steam game shortcuts (`shortcuts.vdf`), custom grid artwork, and Steam library collections from v2 JSON manifests or piped JSON.

## What It Does

- Creates, updates, and prunes non-Steam game shortcuts in Steam's `shortcuts.vdf` and groups them into Steam collections by platform/source.
- Copies custom vertical covers, heroes, logos, and icons into `userdata/<steam3_id>/config/grid/`.
- Supports batch manifest updates (`manifest`), single-game updates from stdin JSON (`direct`), shortcut removal (`remove`), and an interactive Textual TUI (`tui.bat`).
- Refuses to modify `shortcuts.vdf` or collection files while the Steam client is running so Steam doesn't overwrite pending changes.

---

## Requirements

**Windows only.** Reads and writes Windows Steam client `shortcuts.vdf`, user grid folders, and cloud storage files.

- [Python](https://www.python.org/) 3.11–3.13 (in `PATH` or configured via `.python-path`)
- [Poetry](https://python-poetry.org/) (installed globally)
- **Steam Client:** Closed when writing shortcuts or collections (set your account via `STEAM3_ID` in `.env` or `steam3_id` in `config.toml`; auto-detected from `userdata/` when unset)

## Installation

Run `setup.bat` from the repository root to create `.venv/`, install dependencies, and copy `.dist` config templates:

```powershell
setup.bat
```

Use `setup.bat --dev` to include `pytest` and `ruff`, or `setup.bat --config` to only create missing config files.

### Configuration Templates

| Template | Live File | Purpose |
| :--- | :--- | :--- |
| `.env.dist` | `.env` | Target Steam3 account ID (`STEAM3_ID`). |
| `config.dist.toml` | `config.toml` | Steam and Epic paths, fallback `steam3_id`, platform names, and source names. |
| `manifests.dist.toml` | `manifests.toml` | Registered manifest entries and paths to their JSON files. |
| `manifest.dist.json` | `manifest.json` | Sample single-source v2 manifest copied as a starting manifest. |

## Configuration

### 1. Steam3 Account (`.env`)

Edit `.env` at the repository root to specify your Steam3 ID:

```dotenv
STEAM3_ID=your_steam3_id
```

### 2. Paths & Mappings (`config.toml`)

Edit `config.toml` to configure Steam/Epic paths and collection display names (`config.dist.toml` also maps `exoappleiigs`, `exodos`, `exodreamm`, `exoscummvm`, `exowin3x`, and `exowin9x`):

```toml
[defaults]
steam_dir = "C:\\Program Files (x86)\\Steam"
steam3_id = ""
epic_data_dir = "C:\\ProgramData\\Epic"

[platforms]
windows = "Windows"

[sources]
amazon = "Amazon Games"
depot = "Depot"
epic = "Epic Games"
gog = "GOG.com"
local = "Local"
steam = "Steam"
xbox = "Xbox"
```

| Key | Default | Purpose |
| :--- | :--- | :--- |
| `[defaults].steam_dir` | `C:\Program Files (x86)\Steam` | Root Steam installation directory. |
| `[defaults].steam3_id` | `""` (auto-detect) | Fallback Steam3 ID when `STEAM3_ID` in `.env`/environment is unset. |
| `[defaults].epic_data_dir` | `C:\ProgramData\Epic` | Epic Games launcher data directory used to detect Epic-managed installs. |
| `[defaults].epic_launcher_manifests_dir` | `""` (derived) | Optional override for Epic `.item` manifest directory. |
| `[platforms]` | `windows = "Windows"` | Maps manifest platform keys to display names. |
| `[sources]` | `amazon`, `depot`, `epic`, `exo*`, `gog`, ... | Maps manifest `game_source` keys to Steam collection names. |

### 3. Manifest Sources (`manifests.toml`)

Register the manifests you want to read (for example GameBox `data/sources/<game_source>/manifest.json`):

```toml
[windows.local]
manifest_name = "Windows - Local"
manifest_path = "manifest.dist.json"
```

---

## Usage

Run commands via `run.bat <command>` or open the TUI with `tui.bat`:

### Interactive TUI

```powershell
.\tui.bat
```

### CLI Commands

```powershell
# Update shortcuts and collections across all registered manifests
.\run.bat update

# Update one manifest entry with debug logging
.\run.bat manifest -m windows.local -v

# Filter by platform, source, or game ID and prune missing installs
.\run.bat manifest --platform-type windows --source-type local --prune --steam3-id 12345678

# Update a single game shortcut from JSON on stdin
.\run.bat direct < game.json

# Remove shortcuts matching a single game directory
.\run.bat remove --game-dir "C:\Games\Example"

# Remove shortcuts in bulk from a JSON list of game directories
.\run.bat remove --batch < dirs.json
```

## CLI Reference

| Command | Description |
| :--- | :--- |
| `manifest [-m <type>] [-p <platform>] [-s <source>] [-g <id>] [--prune] [--steam3-id <id>] [-v]` | Sync shortcuts and collections from `manifests.toml` (default mode if omitted; `run.bat update` runs `manifest`). |
| `direct [--steam3-id <id>] [-v]` | Create or update a single game shortcut from JSON on stdin. |
| `remove (--game-dir <path> \| --batch [--prune-source <source>]) [--steam3-id <id>] [-v]` | Remove shortcuts by directory or JSON array on stdin (`--prune-source` keeps active dirs for that source and removes orphans). |
| `-v, --verbose` | Enable debug logging across top-level and subcommands. |
| `--steam3-id <id>` | Override target Steam3 account ID for the command. |
| `-h, --help` | Show CLI usage and options. |

## Related Projects

- **[`game-box`](https://github.com/capt-cucumbers/game-box)** — Desktop/web library manager that builds source manifests and can call this tool through its `nonsteamupdater` module.
