"""The command board.

One table, traffic lights, keyboard-driven. Green means sent, red means dead,
yellow means it wants something from you today.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import DataTable, Footer, Header, Static

from jobagent.application.handoff import build_prompt, copy_to_clipboard, open_posting
from jobagent.core.storage import Storage
from jobagent.tracking.board import LIGHTS, State, light_for
from jobagent.tracking.repo import BoardRepo


class Board(App[None]):
    CSS = """
    Screen { background: $surface; }
    #summary { padding: 0 1; height: 1; color: $text-muted; }
    #status { padding: 0 1; height: 1; color: $text; }
    DataTable { height: 1fr; }
    """

    BINDINGS: ClassVar = [
        Binding("a", "state('applied')", "Applied"),
        Binding("w", "state('waiting')", "Waiting"),
        Binding("n", "state('ready')", "Needs me"),
        Binding("r", "state('rejected')", "Rejected"),
        Binding("i", "state('interview')", "Interview"),
        Binding("s", "state('skipped')", "Skip"),
        Binding("o", "open_posting", "Open"),
        Binding("c", "claude", "Apply w/ Claude"),
        Binding("h", "toggle_closed", "Hide/show closed"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.store = Storage()
        self.repo = BoardRepo(self.store)
        self.show_closed = True
        self._row_ids: list[int] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Container(Static("", id="summary"), Static("", id="status"))
        yield DataTable(cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Job board"
        table = self.query_one(DataTable)
        table.add_columns(" ", "Company", "Role", "Location", "Deadline", "Status")
        self.refresh_board()

    # -- rendering ---------------------------------------------------------

    def refresh_board(self, keep_job_id: int | None = None) -> None:
        """Redraw. ``keep_job_id`` holds the cursor on a row that just moved.

        Marking a row re-sorts the board, which would otherwise yank the row out
        from under the cursor mid-triage.
        """
        table = self.query_one(DataTable)
        table.clear()
        self._row_ids = []
        jobs = self.repo.all(include_closed=self.show_closed)
        for job in jobs:
            lamp = light_for(job.state)
            table.add_row(
                f"[{lamp.colour}]{lamp.dot}[/]",
                job.company,
                job.title,
                job.location or "—",
                job.deadline or "—",
                f"[{lamp.colour}]{lamp.label}[/]",
            )
            self._row_ids.append(job.id)

        counts = self.repo.counts()
        parts = []
        for state in (
            State.READY,
            State.APPLIED,
            State.WAITING,
            State.INTERVIEW,
            State.OFFER,
            State.REJECTED,
        ):
            n = counts.get(str(state), 0)
            if n:
                lamp = LIGHTS[state]
                parts.append(f"[{lamp.colour}]{lamp.dot} {n} {lamp.label.lower()}[/]")
        total = sum(counts.values())
        summary = "   ".join(parts) if parts else "no opportunities yet"
        self.query_one("#summary", Static).update(f"{total} tracked    {summary}")

        if keep_job_id is not None and keep_job_id in self._row_ids:
            table.move_cursor(row=self._row_ids.index(keep_job_id))

    def _selected(self) -> int | None:
        table = self.query_one(DataTable)
        if not self._row_ids or table.cursor_row is None:
            return None
        if not 0 <= table.cursor_row < len(self._row_ids):
            return None
        return self._row_ids[table.cursor_row]

    def _say(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    # -- actions -----------------------------------------------------------

    def action_state(self, state: str) -> None:
        job_id = self._selected()
        if job_id is None:
            self._say("Nothing selected.")
            return
        self.repo.set_state(job_id, State(state))
        job = self.repo.get(job_id)
        self.refresh_board(keep_job_id=job_id)
        if job:
            self._say(f"{job.company} → {light_for(state).label.lower()}")

    def action_open_posting(self) -> None:
        job_id = self._selected()
        job = self.repo.get(job_id) if job_id else None
        if job is None or not job.url:
            self._say("No URL on this row.")
            return
        self._say(f"Opening {job.company}…" if open_posting(job.url) else "Could not open browser.")

    def action_claude(self) -> None:
        """Open the posting and stage the prompt for Claude in Chrome."""
        job_id = self._selected()
        job = self.repo.get(job_id) if job_id else None
        if job is None:
            self._say("Nothing selected.")
            return
        prompt = build_prompt(job.company, job.title, job.url)
        tool = copy_to_clipboard(prompt)
        if job.url:
            open_posting(job.url)
        if tool:
            self._say("Prompt copied — paste it into Claude in Chrome, then press 'a' once sent.")
        else:
            self.exit(message=prompt)

    def action_toggle_closed(self) -> None:
        self.show_closed = not self.show_closed
        self.refresh_board()
        self._say("Showing all." if self.show_closed else "Hiding rejected and skipped.")

    def on_unmount(self) -> None:
        self.store.close()


def run() -> None:
    Board().run()
