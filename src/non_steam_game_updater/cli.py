import argparse
import json
import logging
import sys
from dataclasses import asdict
from typing import Any

from non_steam_game_updater.core.config import MANIFEST_PATHS
from non_steam_game_updater.core.logger import setup_logger
from non_steam_game_updater.core.utils import enable_ansi_utf8
from non_steam_game_updater.models import GameInput, ManifestConfig
from non_steam_game_updater.steam.non_steam_game_manager import NonSteamGameManager
from non_steam_game_updater.tasks import run_update_shortcut_from_dict_task, run_update_shortcuts_task

enable_ansi_utf8()

logger = logging.getLogger(__name__)


def main() -> None:
    """Parse CLI arguments and dispatch to the requested mode."""
    verbose_parent = argparse.ArgumentParser(add_help=False)
    verbose_parent.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Enable verbose (DEBUG) logging",
    )

    # Common parser for shared action flags
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "--steam3-id",
        type=str,
        help="Target Steam account Steam3 ID",
    )

    # Main parser
    parser = argparse.ArgumentParser(description="Steam Non-Steam Game Updater CLI tool")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    # Subparsers for commands/modes
    subparsers = parser.add_subparsers(dest="mode", help="Execution mode command")

    # 1. Manifest subcommand
    manifest_parser = subparsers.add_parser(
        "manifest",
        parents=[verbose_parent, common_parser],
        help="Process games using configurations defined in manifest files",
    )
    manifest_parser.add_argument(
        "--manifest-type",
        "-m",
        type=str,
        help="Specific manifest type to process. If omitted, all manifests are processed.",
    )
    manifest_parser.add_argument("--game-id", "-g", type=str, help="Specific Game ID of game to process")
    manifest_parser.add_argument(
        "--platform-type",
        "-p",
        type=str,
        help="Platform type to filter by (e.g. 'windows')",
    )
    manifest_parser.add_argument(
        "--source-type",
        "-s",
        type=str,
        help="Source type to filter by (e.g. 'local')",
    )
    manifest_parser.add_argument(
        "--prune",
        action="store_true",
        help="Remove Steam shortcuts for a manifest source when no longer installed/present",
    )

    # 2. Direct subcommand
    subparsers.add_parser(
        "direct",
        parents=[verbose_parent, common_parser],
        help="Process a single game using JSON configuration from stdin",
    )

    # 3. Remove subcommand
    remove_parser = subparsers.add_parser(
        "remove",
        parents=[verbose_parent, common_parser],
        help="Remove game shortcuts from Steam",
    )
    remove_parser.add_argument(
        "--game-dir",
        type=str,
        help="Directory of the game to remove",
    )
    remove_parser.add_argument(
        "--batch",
        action="store_true",
        help="If set, reads a JSON list of game directories from stdin",
    )
    remove_parser.add_argument(
        "--prune-source",
        type=str,
        help="When combined with --batch, keep active game directories for this source and remove orphans",
    )

    args = parser.parse_args()

    if not args.mode:
        args.mode = "manifest"

    setup_logger(verbose=args.verbose)

    # Direct mode execution
    if args.mode == "direct":
        try:
            raw_data = sys.stdin.read()
            if not raw_data.strip():
                logger.error("No stdin data provided.")
                sys.exit(1)
            raw_dict = json.loads(raw_data)

            game = GameInput.from_dict(raw_dict)
            game_dict = asdict(game)
        except json.JSONDecodeError:
            logger.error("Input is not valid JSON.")
            sys.exit(1)
        except ValueError as e:
            logger.error(f"Validation failed: {e}")
            sys.exit(1)

        if getattr(args, "steam3_id", None):
            ok = run_update_shortcut_from_dict_task(game_dict, steam3_id=args.steam3_id)
        else:
            ok = run_update_shortcut_from_dict_task(game_dict)
        if ok is False:
            sys.exit(1)
        return

    # Remove mode execution
    if args.mode == "remove":
        nsgm = NonSteamGameManager(steam3_id=args.steam3_id)

        if args.game_dir:
            app_ids = nsgm.find_shortcuts_by_game_dir(args.game_dir)
            if app_ids:
                for app_id in app_ids:
                    nsgm.remove(app_id)
                nsgm.save(update_artwork=True)
                logger.info(f"Removed shortcut(s) for game directory: {args.game_dir}")
            else:
                logger.info("No shortcuts found to remove.")
            return

        if args.batch:
            try:
                raw_data = sys.stdin.read()
                if not raw_data.strip():
                    logger.error("No stdin data provided for batch remove.")
                    sys.exit(1)
                remove_dirs = json.loads(raw_data)
                if not isinstance(remove_dirs, list):
                    logger.error("Input must be a JSON array of directories.")
                    sys.exit(1)

                if args.prune_source:
                    removed_ids = nsgm.prune_shortcuts_by_source(args.prune_source, remove_dirs)
                    if removed_ids:
                        nsgm.save(update_artwork=True)
                    logger.info(f"Pruned {len(removed_ids)} orphan shortcut(s) for source '{args.prune_source}'.")
                    return

                modified = False
                for game_dir in remove_dirs:
                    app_ids = nsgm.find_shortcuts_by_game_dir(game_dir)
                    if app_ids:
                        for app_id in app_ids:
                            nsgm.remove(app_id)
                        modified = True
                if modified:
                    nsgm.save(update_artwork=True)
                logger.info(f"Batch removed shortcuts for {len(remove_dirs)} directories.")
                return
            except json.JSONDecodeError:
                logger.error("Input is not valid JSON.")
                sys.exit(1)
        else:
            logger.error("Must specify either --game-dir or --batch.")
            sys.exit(1)

    # Manifest mode execution
    configs: dict[str, ManifestConfig] = MANIFEST_PATHS
    if not configs:
        logger.error("No configurations found in manifests.toml")
        sys.exit(1)

    # Resolve target configs
    if args.manifest_type:
        if args.manifest_type not in configs:
            logger.error(f"Could not find configuration matching manifest type: '{args.manifest_type}'")
            sys.exit(1)
        manifest_configs = {args.manifest_type: configs[args.manifest_type]}
    else:
        manifest_configs = configs

    task_kwargs: dict[str, Any] = {
        "filter_game_id": args.game_id,
        "filter_platform_type": args.platform_type,
        "filter_source_type": args.source_type,
    }
    if args.prune:
        task_kwargs["prune"] = True
    if getattr(args, "steam3_id", None):
        task_kwargs["steam3_id"] = args.steam3_id

    if (
        run_update_shortcuts_task(
            manifest_configs,
            **task_kwargs,
        )
        is False
    ):
        sys.exit(1)


if __name__ == "__main__":
    main()
