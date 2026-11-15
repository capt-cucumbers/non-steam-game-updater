from pathlib import Path

from textual.app import App

from non_steam_game_updater.ui.screens.screens import MainMenuScreen


class NonSteamUpdaterApp(App):
    """Textual TUI application for the Non-Steam Game Updater."""

    TITLE = "NON-STEAM GAME UPDATER"
    ENABLE_COMMAND_PALETTE = True
    CSS_PATH = str(Path(__file__).parent / "style.tcss")

    def on_mount(self) -> None:
        self.theme = "textual-dark"
        self.push_screen(MainMenuScreen())
