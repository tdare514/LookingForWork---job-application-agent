"""CLI entry point.

The full command surface lands in #26 (Day 2). Day 1 ships only what proves the
foundation works: initialise the data directory, show status, read the audit log.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from jobagent.application.answers import standing_answers
from jobagent.application.package import build as build_package
from jobagent.application.resume import load as load_resume
from jobagent.application.tailor import Posting
from jobagent.core.paths import default_data_dir, ensure_data_dir
from jobagent.core.pii import REGISTRY
from jobagent.core.storage import Storage
from jobagent.tracking.board import State, light_for
from jobagent.tracking.repo import BoardRepo

app = typer.Typer(help="Personal, human-in-the-loop job application agent.", no_args_is_help=True)
console = Console()


@app.command()
def init() -> None:
    """Create the data directory and apply migrations."""
    data_dir = ensure_data_dir()
    with Storage() as store:
        version = store.schema_version()
        store.append_audit("init", {"data_dir": str(data_dir), "schema_version": version})
    console.print(f"[green]Initialised[/green] {data_dir}")
    console.print(f"Schema version: {version}")


@app.command()
def status() -> None:
    """Show where data lives and what is in it."""
    data_dir = default_data_dir()
    if not data_dir.exists():
        console.print("[yellow]Not initialised.[/yellow] Run `jobagent init`.")
        raise typer.Exit(code=1)

    with Storage() as store:
        table = Table(title="jobagent status")
        table.add_column("Item")
        table.add_column("Value")
        table.add_row("Data directory", str(data_dir))
        table.add_row("Schema version", str(store.schema_version()))
        table.add_row("Jobs", str(store.count("jobs")))
        table.add_row("Applications", str(store.count("applications")))
        table.add_row("Audit entries", str(store.count("audit_log")))
        console.print(table)


@app.command()
def audit(limit: int = 20) -> None:
    """Read the append-only audit trail."""
    with Storage() as store:
        entries = store.audit_entries(limit=limit)
    if not entries:
        console.print("[yellow]No audit entries.[/yellow]")
        return
    table = Table(title="Audit trail")
    table.add_column("When")
    table.add_column("Action")
    table.add_column("Detail")
    for entry in entries:
        table.add_row(entry["occurred_at"], entry["action"], str(entry["detail"]))
    console.print(table)


@app.command("pii")
def pii_inventory() -> None:
    """Print the PII inventory -- what is stored, why, and for how long."""
    table = Table(title="PII inventory")
    table.add_column("Field")
    table.add_column("Sensitivity")
    table.add_column("May reach")
    table.add_column("Retention")
    for field in REGISTRY:
        retention = "until deleted" if field.retention_days is None else f"{field.retention_days}d"
        table.add_row(
            f"{field.table}.{field.column}",
            field.sensitivity.value,
            ", ".join(d.value for d in field.destinations),
            retention,
        )
    console.print(table)


@app.command()
def add(
    company: str = typer.Option(..., "--company", "-c", help="Employer name."),
    title: str = typer.Option(..., "--title", "-t", help="Role title."),
    url: str = typer.Option(None, "--url", "-u", help="Link to the posting."),
    location: str = typer.Option(None, "--location", "-l"),
    deadline: str = typer.Option(None, "--deadline", "-d", help="YYYY-MM-DD."),
    ready: bool = typer.Option(False, "--ready", help="Mark as needing action now."),
) -> None:
    """Add an opportunity to the board."""
    with Storage() as store:
        repo = BoardRepo(store)
        job, created = repo.add(
            company=company,
            title=title,
            url=url,
            location=location,
            deadline=deadline,
            state=State.READY if ready else State.NEW,
        )
    lamp = light_for(job.state)
    verb = "Added" if created else "Already tracked"
    console.print(f"[{lamp.colour}]{lamp.dot}[/] {verb}: [bold]{job.company}[/] — {job.title}")


resume_app = typer.Typer(help="The resume source of truth.", no_args_is_help=True)
app.add_typer(resume_app, name="resume")


@resume_app.command("validate")
def resume_validate(
    path: Path = typer.Argument(None, help="Defaults to <data dir>/resume.yaml."),
) -> None:
    """Validate the resume source of truth. A bad resume fails loudly."""
    target = path or (default_data_dir() / "resume.yaml")
    try:
        resume = load_resume(target)
    except FileNotFoundError:
        console.print(f"[red]No resume at[/red] {target}")
        console.print("Start from the example: [bold]cp resume.example.yaml[/bold] " + str(target))
        raise typer.Exit(code=1) from None
    except Exception as exc:  # pydantic/yaml errors carry the field name
        console.print(f"[red]Invalid resume[/red] at {target}:\n{exc}")
        raise typer.Exit(code=1) from None

    accomplishments = resume.all_accomplishments()
    unmeasured = [a.id for a in accomplishments if a.metric is None]
    table = Table(title=f"Resume valid — {resume.contact.name}")
    table.add_column("Item")
    table.add_column("Value")
    table.add_row("Roles", str(len(resume.roles)))
    table.add_row("Projects", str(len(resume.projects)))
    table.add_row("Accomplishments", str(len(accomplishments)))
    table.add_row("With a measurement", str(len(accomplishments) - len(unmeasured)))
    console.print(table)
    if unmeasured:
        console.print(
            f"[yellow]{len(unmeasured)} accomplishment(s) carry no metric.[/yellow] "
            "That is allowed — tailoring will not invent one."
        )


@app.command()
def draft(
    job_id: int = typer.Argument(..., help="Board row to draft for (see `jobagent list`)."),
    description: Path = typer.Option(
        None, "--description", "-D", help="File with the posting text, for better targeting."
    ),
    resume_path: Path = typer.Option(None, "--resume", help="Defaults to <data dir>/resume.yaml."),
    bullets: int = typer.Option(4, "--bullets", help="Max bullets per role."),
) -> None:
    """Build a complete application package: tailored resume, cover letter, answers."""
    data_dir = default_data_dir()
    target = resume_path or (data_dir / "resume.yaml")
    try:
        resume = load_resume(target)
    except FileNotFoundError:
        console.print(f"[red]No resume at[/red] {target}")
        console.print("Start from the example: [bold]cp resume.example.yaml[/bold] " + str(target))
        raise typer.Exit(code=1) from None

    with Storage() as store:
        job = BoardRepo(store).get(job_id)
    if job is None:
        console.print(f"[red]No job {job_id} on the board.[/red]")
        raise typer.Exit(code=1)

    posting = Posting(
        company=job.company,
        title=job.title,
        description=description.read_text() if description else "",
    )
    library = standing_answers(
        authorization=resume.standing.authorization,
        availability=resume.standing.availability,
        term_lengths=resume.standing.term_lengths,
        notice=resume.standing.notice,
        compensation=resume.standing.compensation,
        relocation=resume.standing.relocation,
    )

    out_dir = data_dir / "packages" / f"{job.id}-{job.company.lower().replace(' ', '-')}"
    package = build_package(resume, posting, library, out_dir, max_bullets_per_role=bullets)

    with Storage() as store:
        store.append_audit(
            "package.build",
            {"job_id": job.id, "company": job.company, "directory": str(out_dir)},
        )

    table = Table(title=f"Package ready — {job.company}")
    table.add_column("Item")
    table.add_column("Value")
    for label, value in package.summary():
        table.add_row(label, value)
    console.print(table)
    console.print(f"\n[green]Written to[/green] {out_dir}")
    console.print(
        "[yellow]Two things still need you:[/yellow] the company paragraph in the "
        "cover letter, and the 'why this company' answer."
    )


@app.command("export")
def export_cmd(
    destination: Path = typer.Argument(..., help="Directory to write the archive into."),
) -> None:
    """Archive the whole data directory to one portable file."""
    from jobagent.core.lifecycle import export as run_export

    archive = run_export(destination)
    console.print(f"[green]Exported[/green] {archive}")
    console.print(
        "[yellow]This archive is the most sensitive file this tool produces.[/yellow] "
        "It contains your full application history."
    )


@app.command("purge")
def purge_cmd(
    yes: bool = typer.Option(False, "--yes", help="Required. Purge never runs unattended."),
) -> None:
    """Delete the dossier, then verify nothing recoverable remains."""
    from jobagent.core.lifecycle import purge as run_purge

    data_dir = default_data_dir()
    if not yes:
        console.print(f"This deletes everything under [bold]{data_dir}[/bold]:")
        console.print("  profile, resume, jobs, application history, documents, audit log.")
        console.print("Re-run with [bold]--yes[/bold] if that is what you want.")
        raise typer.Exit(code=1)

    report = run_purge()
    console.print(
        f"[green]Removed[/green] {report.removed_files} file(s), "
        f"{report.removed_bytes / 1024:.0f} KB."
    )
    if report.clean:
        console.print("[green]Verified: nothing recoverable remains.[/green]")
    else:
        console.print(f"[red]Survived purge:[/red] {report.remaining}")
        raise typer.Exit(code=1)


@app.command()
def fetch(
    source: str = typer.Argument(
        ..., help="Adapter name, e.g. workday:rbc, or 'all' for every Workday tenant."
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Max postings to pull."),
    match: str = typer.Option(None, "--match", "-m", help="Only keep titles containing this text."),
) -> None:
    """Pull postings from a source onto the board.

    Nothing is applied to; rows land as `new` for you to triage.
    """
    from jobagent.discovery.http import HostNotAllowed, PoliteClient, SourceDeclined
    from jobagent.discovery.workday import ALL as WORKDAY_ALL

    adapters = (
        list(WORKDAY_ALL) if source == "all" else [a for a in WORKDAY_ALL if a.name == source]
    )
    if not adapters:
        console.print(f"[red]Unknown source[/red] {source!r}.")
        console.print("Known: " + ", ".join(a.name for a in WORKDAY_ALL) + ", or 'all'.")
        raise typer.Exit(code=1)

    hosts = {h for a in adapters for h in a.hosts}
    added = skipped = 0
    with Storage() as store, PoliteClient(hosts, min_interval_seconds=2.0) as client:
        repo = BoardRepo(store)
        for adapter in adapters:
            try:
                postings = list(adapter.fetch(client, limit=limit))
            except SourceDeclined as exc:
                # One tenant refusing says nothing about the others, so keep going.
                console.print(f"[yellow]{adapter.name} declined:[/yellow] {exc}")
                console.print("[dim]Use the board's `c` handoff for this one instead.[/dim]")
                continue
            except HostNotAllowed as exc:
                console.print(f"[red]{adapter.name}:[/red] {exc}")
                continue
            except Exception as exc:  # schema drift -- loud, not silent
                console.print(f"[red]{adapter.name} returned an unexpected shape:[/red] {exc}")
                continue

            for posting in postings:
                if match and match.lower() not in posting.title.lower():
                    continue
                _job, created = repo.add(
                    company=posting.company,
                    title=posting.title,
                    url=posting.url,
                    location=posting.location,
                )
                added += created
                skipped += not created
            store.append_audit("fetch", {"source": adapter.name, "returned": len(postings)})

    console.print(f"[green]{added} new[/green], {skipped} already tracked.")
    if added:
        console.print("Run [bold]jobagent board[/bold] to triage them.")


@app.command()
def report() -> None:
    """Funnel: what is converting, and what is not."""
    from jobagent.tracking.funnel import SMALL_SAMPLE
    from jobagent.tracking.funnel import build as build_report

    with Storage() as store:
        data = build_report(BoardRepo(store).all())

    if data.total == 0:
        console.print("[yellow]Nothing tracked yet.[/yellow] Add a role with `jobagent add`.")
        return

    funnel = Table(title="Funnel")
    funnel.add_column("Stage")
    funnel.add_column("Reached", justify="right")
    funnel.add_column("From previous", justify="right")
    for stage in data.stages:
        if stage.conversion is None:
            rate = "—"
        else:
            # The denominator is part of the number. A bare percentage off four
            # rows reads like evidence when it is not.
            note = " [dim](thin)[/]" if stage.thin else ""
            rate = f"{stage.conversion:.0%} of {stage.previous_total}{note}"
        funnel.add_row(stage.state.value.title(), str(stage.reached), rate)
    console.print(funnel)

    outcomes = Table(title="Outcomes")
    outcomes.add_column("Item")
    outcomes.add_column("Count", justify="right")
    outcomes.add_row("Tracked", str(data.total))
    outcomes.add_row("Not yet triaged", str(data.untriaged))
    outcomes.add_row("[red]Rejected[/]", str(data.rejected))
    outcomes.add_row("Skipped", str(data.skipped))
    outcomes.add_row("[yellow]Stale (30d+)[/]", str(data.stale))
    if data.median_days_in_state is not None:
        outcomes.add_row("Median days in state", str(data.median_days_in_state))
    console.print(outcomes)

    if data.by_company:
        companies = Table(title="By company — ranked by applications, not rows")
        companies.add_column("Company")
        companies.add_column("Tracked", justify="right")
        companies.add_column("Applied", justify="right")
        for name, tracked, applied in data.by_company[:10]:
            companies.add_row(name, str(tracked), str(applied))
        console.print(companies)

    if not data.has_outcomes:
        console.print(
            "\n[yellow]Nothing submitted yet[/yellow] — the rates above are "
            "structure, not signal. Come back once applications are out."
        )
    elif data.thin_overall:
        console.print(
            f"\n[yellow]Fewer than {SMALL_SAMPLE} tracked roles.[/yellow] Treat every "
            "percentage here as a hint, not a finding."
        )


@app.command()
def followups() -> None:
    """What wants a follow-up today, most overdue first."""
    from jobagent.tracking.followups import due

    with Storage() as store:
        items = due(BoardRepo(store).all())
    if not items:
        console.print("[green]Nothing overdue.[/green]")
        return
    table = Table(title="Follow-ups due")
    table.add_column("Company")
    table.add_column("Role")
    table.add_column("Days")
    table.add_column("What to do")
    for item in items:
        colour = "red" if item.stale else "yellow"
        table.add_row(
            item.job.company,
            item.job.title,
            f"[{colour}]{item.days_in_state}[/]",
            item.reason,
        )
    console.print(table)
    console.print("[dim]The agent drafts and reminds. Sending is yours.[/dim]")


@app.command()
def board() -> None:
    """Open the command board."""
    data_dir = default_data_dir()
    if not data_dir.exists():
        console.print("[yellow]Not initialised.[/yellow] Run `jobagent init`.")
        raise typer.Exit(code=1)
    from jobagent.tracking.app import run

    run()


@app.command("list")
def list_jobs() -> None:
    """Print the board without the interactive UI."""
    with Storage() as store:
        jobs = BoardRepo(store).all()
    if not jobs:
        console.print("[yellow]Nothing tracked yet.[/yellow] Add one with `jobagent add`.")
        return
    table = Table(title="Job board")
    table.add_column(" ")
    table.add_column("Company")
    table.add_column("Role")
    table.add_column("Deadline")
    table.add_column("Status")
    for job in jobs:
        lamp = light_for(job.state)
        table.add_row(
            f"[{lamp.colour}]{lamp.dot}[/]",
            job.company,
            job.title,
            job.deadline or "—",
            f"[{lamp.colour}]{lamp.label}[/]",
        )
    console.print(table)


if __name__ == "__main__":
    app()
