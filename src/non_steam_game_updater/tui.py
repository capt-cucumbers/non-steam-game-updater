from non_steam_game_updater.core.logger import setup_logger
from non_steam_game_updater.core.utils import enable_ansi_utf8
from non_steam_game_updater.ui.app import NonSteamUpdaterApp

enable_ansi_utf8()

setup_logger(verbose=False, console=False)


def main() -> None:
    """Launch the Textual application."""
    app = NonSteamUpdaterApp()
    app.run()


if __name__ == "__main__":
    main()
