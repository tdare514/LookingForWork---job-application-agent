from __future__ import annotations

from jobagent.application.handoff import build_prompt
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


def test_handoff_prompt_forbids_submitting_and_inventing() -> None:
    """The gate is in the prompt because the human is the gate."""
    prompt = build_prompt("BMO", "Business Analyst", "https://example.com")
    assert "Do not click the final submit button." in prompt
    assert "Do not invent anything about my experience." in prompt
    assert "dareoluwatoby@gmail.com" in prompt


def test_handoff_prompt_carries_the_recurring_answers() -> None:
    prompt = build_prompt("RBC", "Business Systems Analyst", None)
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
