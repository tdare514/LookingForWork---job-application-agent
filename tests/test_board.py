from __future__ import annotations

from pathlib import Path

from jobagent.application.handoff import Applicant, applicant_from, build_prompt
from jobagent.core.storage import Storage
from jobagent.tracking.board import State, light_for
from jobagent.tracking.repo import BoardRepo


def test_add_and_list(store: Storage) -> None:
    repo = BoardRepo(store)
    job, created = repo.add("BMO", "Business Analyst, Winter 2027", url="https://x")
    assert created and job.state == State.NEW
    assert [j.company for j in repo.all()] == ["BMO"]


def test_re_adding_the_same_role_does_not_duplicate(store: Storage) -> None:
    repo = BoardRepo(store)
    repo.add("BMO", "Business Analyst, Winter 2027")
    _, created = repo.add("BMO  Inc.", "business analyst, winter 2027")
    assert created is False
    assert len(repo.all()) == 1


def test_different_roles_at_one_company_stay_separate(store: Storage) -> None:
    repo = BoardRepo(store)
    repo.add("RBC", "Business Systems Analyst")
    repo.add("RBC", "Technical Systems Analyst")
    assert len(repo.all()) == 2


def test_needs_action_sorts_above_everything_else(store: Storage) -> None:
    repo = BoardRepo(store)
    a, _ = repo.add("Applied Co", "Role A")
    b, _ = repo.add("Needy Co", "Role B")
    c, _ = repo.add("Dead Co", "Role C")
    repo.set_state(a.id, State.APPLIED)
    repo.set_state(b.id, State.READY)
    repo.set_state(c.id, State.REJECTED)
    assert [j.company for j in repo.all()] == ["Needy Co", "Applied Co", "Dead Co"]


def test_closed_rows_can_be_hidden(store: Storage) -> None:
    repo = BoardRepo(store)
    job, _ = repo.add("Dead Co", "Role")
    repo.set_state(job.id, State.REJECTED)
    assert repo.all(include_closed=False) == []


def test_traffic_lights_match_the_three_questions() -> None:
    """Green means sent, red means dead, yellow means it wants something today."""
    assert light_for("applied").colour == "green"
    assert light_for("interview").colour == "green"
    assert light_for("offer").colour == "green"
    assert light_for("rejected").colour == "red"
    assert light_for("waiting").colour == "yellow"
    assert light_for("ready").colour == "yellow"


def test_state_changes_are_audited(store: Storage) -> None:
    repo = BoardRepo(store)
    job, _ = repo.add("BMO", "Business Analyst")
    repo.set_state(job.id, State.APPLIED)
    actions = [e["action"] for e in store.audit_entries()]
    assert "job.state" in actions and "job.add" in actions


def _applicant() -> Applicant:
    from jobagent.application.resume import load

    resume = load(Path(__file__).resolve().parents[1] / "resume.example.yaml")
    return applicant_from(
        resume,
        authorization=resume.standing.authorization,
        availability=resume.standing.availability,
    )


def test_handoff_prompt_forbids_submitting_and_inventing() -> None:
    """The gate is in the prompt because the human is the gate."""
    prompt = build_prompt("BMO", "Business Analyst", "https://example.com", _applicant())
    assert "Do not click the final submit button." in prompt
    assert "Do not invent anything about my experience." in prompt
    assert "you@example.com" in prompt


def test_handoff_prompt_carries_the_recurring_answers() -> None:
    prompt = build_prompt("RBC", "Business Systems Analyst", None, _applicant())
    assert "Work authorization:" in prompt
    assert "January 2027" in prompt


async def test_board_keybindings_write_through_to_storage(data_dir: object) -> None:
    """The board is not a view -- pressing a key changes the record."""
    from textual.widgets import DataTable

    from jobagent.tracking.app import Board

    with Storage() as setup:
        repo = BoardRepo(setup)
        repo.add("BMO", "Business Analyst")
        repo.add("RBC", "Business Systems Analyst")

    app = Board()
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(DataTable)
        await pilot.press("a")
        await pilot.pause()
        # The cursor must still sit on the row we just marked, not wherever the
        # re-sort moved it.
        marked = app._row_ids[table.cursor_row]
        job = app.repo.get(marked)
        assert job is not None
        assert job.state == "applied"

    with Storage() as check:
        states = sorted(j.state for j in BoardRepo(check).all())
    assert states == ["applied", "new"]


def test_the_board_draft_key_writes_a_package(data_dir: object) -> None:
    """d on the board must produce real files, not just a status line."""
    import shutil
    from pathlib import Path as P

    from textual.widgets import DataTable

    from jobagent.core.paths import ensure_data_dir
    from jobagent.tracking.app import Board

    root = P(__file__).resolve().parents[1]
    shutil.copy(root / "resume.example.yaml", ensure_data_dir() / "resume.yaml")

    with Storage() as setup:
        BoardRepo(setup).add("BMO", "Business Analyst, Winter 2027")

    async def drive() -> None:
        app = Board()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            table = app.query_one(DataTable)
            job_id = app._row_ids[table.cursor_row]
            out = app._package_dir(job_id)
            assert (out / "cover-letter.txt").is_file()
            assert list(out.glob("*.pdf")), "no resume rendered"
            assert list(out.glob("*.docx")), "no docx rendered"

    import asyncio

    asyncio.run(drive())


def test_the_handoff_prompt_points_at_the_drafted_resume() -> None:
    """A prompt telling Claude to upload a file that does not exist is useless."""
    prompt = build_prompt(
        "BMO",
        "Business Analyst",
        "https://example.com",
        _applicant(),
        resume_path=Path("/tmp/example-resume.pdf"),
    )
    assert "/tmp/example-resume.pdf" in prompt


def test_a_missing_clipboard_tool_does_not_quit_the_board(
    data_dir: object, monkeypatch: object
) -> None:
    """Losing your place on the board to dump text to stdout is a bad trade."""
    import asyncio
    import shutil
    from pathlib import Path as P

    import jobagent.tracking.app as app_module
    from jobagent.core.paths import ensure_data_dir
    from jobagent.tracking.app import Board

    root = P(__file__).resolve().parents[1]
    shutil.copy(root / "resume.example.yaml", ensure_data_dir() / "resume.yaml")
    with Storage() as setup:
        BoardRepo(setup).add("BMO", "Business Analyst")

    monkeypatch.setattr(app_module, "copy_to_clipboard", lambda _text: None)  # type: ignore[attr-defined]

    async def drive() -> None:
        app = Board()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("c")
            await pilot.pause()
            assert app.is_running, "the board must stay open without a clipboard"
            from textual.widgets import DataTable

            job_id = app._row_ids[app.query_one(DataTable).cursor_row]
            assert (app._package_dir(job_id) / "claude-prompt.txt").is_file()

    asyncio.run(drive())


async def test_the_table_gets_the_screen_not_the_header(data_dir: object) -> None:
    """The board is the table. Two header lines may not take half the terminal.

    Pinned at two sizes because the failure this guards scaled with the
    terminal: an unset container height took an equal `1fr` share, so a taller
    window spent more of itself on blank space, not more rows.
    """
    from textual.containers import Container
    from textual.widgets import DataTable

    from jobagent.tracking.app import Board

    with Storage() as setup:
        BoardRepo(setup).add("BMO", "Business Analyst")

    for height in (24, 40):
        app = Board()
        async with app.run_test(size=(100, height)) as pilot:
            await pilot.pause()
            meta = app.query_one("#meta", Container)
            table = app.query_one(DataTable)
            assert meta.size.height <= 2, (
                f"the header holds two one-line widgets but took "
                f"{meta.size.height} rows at height {height}"
            )
            assert table.size.height > height // 2
