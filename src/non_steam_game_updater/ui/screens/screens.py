import logging
from collections.abc import Iterable
from typing import ClassVar

from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import DataTable, OptionList, Static
from textual.widgets.option_list import Option

from non_steam_game_updater.core import config
from non_steam_game_updater.models import ManifestConfig
from non_steam_game_updater.tasks import run_update_shortcuts_task
from non_steam_game_updater.ui.screens.base import (
    BaseOptionListScreen,
    BaseSearchTableScreen,
)
from non_steam_game_updater.ui.screens.common import ProgressLogScreen
from non_steam_game_updater.ui.widgets import clean_option_prompt

logger = logging.getLogger(__name__)

BULK_ALL_ID = "__bulk_all__"


class MainMenuScreen(BaseOptionListScreen):
    """The main menu navigation screen for Non-Steam Game Updater."""

    nav_label: str = "HOME"

    def __init__(self) -> None:
        super().__init__()
        self.sub_title = "Non-Steam Game Updater"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Exit"),
    ]

    def compose_body(self) -> Iterable[Widget]:
        yield Static(id="summary")
        yield OptionList(id="options_list")

    def on_mount(self) -> None:
        super().on_mount()
        self.update_summary()

    def on_screen_resume(self) -> None:
        super().on_screen_resume()
        self.update_summary()

    def action_quit(self) -> None:
        self.app.exit()

    def update_summary(self) -> None:
        """Refresh the configured manifest count shown in the summary."""
        total_manifests = len(config.MANIFEST_NAMES)
        summary_text = (
            f"[$text]Non-Steam Game Updater[/] - [$warning]Select a shortcut management operation:[/]\n"
            f"[$text]Configured Manifests:[/] [dim]{total_manifests} manifests available[/dim]"
        )
        self.query_one("#summary", Static).update(summary_text)

    def get_options(self) -> list[Option | None]:
        return [
            Option(
                "[bold $text]▶  RUN SHORTCUT UPDATER (SELECT MANIFEST)[/]\n"
                "   [dim]Select a specific game platform/launcher manifest to sync into Steam[/dim]",
                id="opt_select_manifest",
            ),
            None,
            Option(
                "[bold $text]▶  RUN SHORTCUT UPDATER (BULK ALL MANIFESTS)[/]\n"
                "   [dim]Sync all configured platform manifests and shortcuts into Steam[/dim]",
                id="opt_bulk_all",
            ),
            None,
            Option(
                "[bold $text]▶  LIST CONFIGURED MANIFESTS[/]\n"
                "   [dim]Browse data table of all configured manifest paths and types[/dim]",
                id="opt_list",
            ),
            None,
            Option(
                "[$error]✕  EXIT[/]\n   [dim]Exit Non-Steam Game Updater[/dim]",
                id="opt_exit",
            ),
        ]

    def on_option_selected(self, option_id: str | None, option_prompt: str) -> None:
        if option_id == "opt_select_manifest":
            self.app.push_screen(SelectManifestScreen())
        elif option_id == "opt_bulk_all":
            self.app.push_screen(SelectActionScreen(config.MANIFEST_PATHS, "All Manifests"))
        elif option_id == "opt_list":
            self.app.push_screen(ManifestListScreen())
        elif option_id == "opt_exit":
            self.app.exit()


class SelectManifestScreen(BaseOptionListScreen):
    """Screen for selecting a specific manifest to process."""

    nav_label: str = "TARGET"

    def __init__(self) -> None:
        super().__init__()
        self.sub_title = "Select Manifest Target"

    def compose_body(self) -> Iterable[Widget]:
        yield Static("[$text]Select Target[/] - [$warning]Choose a platform manifest to process:[/]", id="summary")
        yield OptionList(id="options_list")

    def get_options(self) -> list[Option | None]:
        opts: list[Option | None] = []
        for m_type, m_name in sorted(config.MANIFEST_NAMES.items()):
            opts.append(
                Option(
                    f"[bold $text]▶  {m_name.upper()}[/]\n"
                    f"   [dim]Process and update {m_name} shortcut manifest in Steam[/dim]",
                    id=m_type,
                )
            )
            opts.append(None)
        opts.append(
            Option(
                "[bold $text]▶  BULK PROCESS ALL MANIFESTS[/]\n"
                "   [dim]Batch process all registered manifests in a single execution[/dim]",
                id=BULK_ALL_ID,
            )
        )
        return opts

    def on_option_selected(self, option_id: str | None, option_prompt: str) -> None:
        if option_id == BULK_ALL_ID:
            manifest_configs = config.MANIFEST_PATHS
            label = "All Manifests"
        elif option_id:
            manifest_configs = {option_id: config.MANIFEST_PATHS.get(option_id, {})}
            label = clean_option_prompt(option_prompt)
        else:
            return

        self.app.push_screen(SelectActionScreen(manifest_configs, label))


class SelectActionScreen(BaseOptionListScreen):
    """Screen for selecting the action to perform on manifest(s)."""

    nav_label: str = "ACTION"

    def __init__(self, manifest_configs: dict[str, ManifestConfig], manifest_label: str) -> None:
        super().__init__()
        self.sub_title = f"Actions ({manifest_label})"
        self.manifest_configs = manifest_configs
        self.manifest_label = manifest_label

    def compose_body(self) -> Iterable[Widget]:
        yield Static(f"[$text]{self.sub_title}[/] - [$warning]Select an action to execute:[/]", id="summary")
        yield OptionList(id="options_list")

    def get_options(self) -> list[Option | None]:
        return [
            Option(
                "[bold $text]▶  UPDATE SHORTCUTS IN STEAM[/]\n"
                "   [dim]Generate VDF entries, artwork hashes, and update Steam shortcuts[/dim]",
                id="opt_update",
            ),
        ]

    def on_option_selected(self, option_id: str | None, option_prompt: str) -> None:
        if option_id != "opt_update":
            return

        label = self.manifest_label
        title = f"Updating: {label}"

        def task() -> bool:
            return run_update_shortcuts_task(self.manifest_configs)

        self.app.push_screen(ProgressLogScreen(title, task))


class ManifestListScreen(BaseSearchTableScreen):
    """Searchable screen for listing all configured manifests."""

    nav_label: str = "LIST"

    def __init__(self) -> None:
        super().__init__()
        self.sub_title = "Configured Manifests"

    def setup_columns(self, table: DataTable) -> None:
        table.add_columns("Manifest Key", "Manifest Name", "Configured Path")

    def get_records(self) -> list[dict[str, str]]:
        records = []
        for m_type, m_name in sorted(config.MANIFEST_NAMES.items()):
            manifest = config.MANIFEST_PATHS.get(m_type, {})
            path = manifest.get("manifest_path", "Not configured")
            records.append({"key": m_type, "name": m_name, "path": str(path)})
        return records

    def match_record(self, record: dict[str, str], filter_text: str) -> bool:
        term = filter_text.lower()
        return term in record["key"].lower() or term in record["name"].lower() or term in record["path"].lower()

    def add_record_row(self, table: DataTable, record: dict[str, str]) -> None:
        table.add_row(record["key"], record["name"], record["path"], key=record["key"])

    def on_screen_resume(self) -> None:
        super().on_screen_resume()
        self.loading = True
        self.run_worker(self.load_records, thread=True)
