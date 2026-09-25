"""CLI entry point.

The full command surface lands in #26 (Day 2). Day 1 ships only what proves the
foundation works: initialise the data directory, show status, read the audit log.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from rich.console import Console
from rich.table import Table

from jobagent.application.answers import standing_answers
from jobagent.application.package import build as build_package
from jobagent.application.resume import load as load_resume
from jobagent.application.tailor import Posting
from jobagent.core.paths import default_data_dir, ensure_data_dir
from jobagent.core.pii import REGISTRY
from jobagent.core.profile import Profile
from jobagent.core.profile import load as load_stored_profile
from jobagent.core.profile import load_file as load_profile_file
from jobagent.core.profile import store as store_profile
from jobagent.core.storage import Storage
from jobagent.matching.extract import Requirements
from jobagent.tracking.board import State, light_for
from jobagent.tracking.repo import BoardRepo

if TYPE_CHECKING:  # Imported lazily at runtime; the CLI keeps its startup cheap.
    from jobagent.discovery.adapter import RawPosting
    from jobagent.discovery.http import PoliteClient

app = typer.Typer(help="Personal, human-in-the-loop job application agent.", no_args_is_help=True)
console = Console()


@app.command()
def init() -> None:
    """Create the data directory and apply migrations."""
    data_dir = ensure_data_dir()
    with Storage() as store:
        version = store.schema_version()
        # Rows added before M0003 carry no dedupe key. Idempotent; a no-op after
        # the first run. Fills the new columns and merges nothing.
        backfilled = BoardRepo(store).backfill_normalized()
        store.append_audit("init", {"data_dir": str(data_dir), "schema_version": version})
    console.print(f"[green]Initialised[/green] {data_dir}")
    console.print(f"Schema version: {version}")
    if backfilled:
        console.print(f"Normalized {backfilled} existing row(s) for de-duplication.")


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


profile_app = typer.Typer(help="What you are looking for.", no_args_is_help=True)
app.add_typer(profile_app, name="profile")


def _load_profile_or_exit(path: Path | None, *, about_to_store: bool) -> Profile:
    """Load a profile file, or report why not and stop.

    Shared by `validate` and `set` so the two cannot drift into describing the
    same bad file differently -- which is the whole point of having a validate
    command you trust before you store anything.
    """
    target = path or (default_data_dir() / "profile.yaml")
    try:
        return load_profile_file(target)
    except FileNotFoundError:
        console.print(f"[red]No profile at[/red] {target}")
        console.print("Start from the example: [bold]cp profile.example.yaml[/bold] " + str(target))
        raise typer.Exit(code=1) from None
    except Exception as exc:  # pydantic and the secret guard both name the field
        console.print(f"[red]Invalid profile[/red] at {target}:\n{exc}")
        if about_to_store:
            console.print("[dim]Nothing was stored.[/dim]")
        raise typer.Exit(code=1) from None


@profile_app.command("validate")
def profile_validate(
    path: Path = typer.Argument(None, help="Defaults to <data dir>/profile.yaml."),
) -> None:
    """Check a profile file without storing it."""
    profile = _load_profile_or_exit(path, about_to_store=False)
    console.print("[green]Profile valid[/green]")
    _print_profile(profile, stored=False)


@profile_app.command("set")
def profile_set(
    path: Path = typer.Argument(None, help="Defaults to <data dir>/profile.yaml."),
) -> None:
    """Validate a profile file and store it. This is what the agent then reads."""
    profile = _load_profile_or_exit(path, about_to_store=True)
    with Storage() as store:
        store_profile(store, profile)
    console.print(f"[green]Profile stored[/green] — schema v{profile.schema_version}")
    _print_profile(profile, stored=True)


@profile_app.command("show")
def profile_show() -> None:
    """What the agent is actually using, read back from the database."""
    with Storage() as store:
        profile = load_stored_profile(store)
    if profile is None:
        console.print("[yellow]No profile stored.[/yellow]")
        console.print("Set one with [bold]jobagent profile set <file>[/bold].")
        raise typer.Exit(code=1)
    _print_profile(profile, stored=True)


def _print_profile(profile: Profile, *, stored: bool) -> None:
    """Summarise a profile. Compensation and work authorization are named, not
    printed: they are the two highest-sensitivity fields in the dossier, and a
    terminal is a place people screen-share."""
    table = Table(title="Profile" + ("" if stored else " (not stored)"))
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Titles", ", ".join(profile.target_titles))
    table.add_row("Seniority", ", ".join(s.value for s in profile.target_seniority))
    table.add_row("Locations", ", ".join(profile.locations))
    table.add_row("Arrangements", ", ".join(profile.work_arrangements))
    table.add_row("Must have", ", ".join(profile.must_have_skills))
    table.add_row("Nice to have", ", ".join(profile.nice_to_have_skills) or "—")
    table.add_row("Deal-breakers", ", ".join(profile.deal_breakers) or "—")
    table.add_row("Blocked companies", str(len(profile.company_blocklist)))
    table.add_row(
        "Compensation floor",
        "set" if profile.compensation.floor is not None else "none stated",
    )
    table.add_row(
        "Sponsorship needed",
        "yes" if profile.work_authorization.needs_sponsorship else "no",
    )
    console.print(table)

    weights = Table(title="Scoring weights — normalized")
    weights.add_column("Component")
    weights.add_column("Share", justify="right")
    for name, share in profile.weights.normalized().items():
        label = name.replace("_", " ")
        note = " [dim](no backend yet — #31)[/]" if name == "semantic_fit" else ""
        weights.add_row(label + note, f"{share:.0%}")
    console.print(weights)


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


# What a hosted purge cannot reach, said plainly rather than implied away.
HOSTED_PURGE_LIMITS = (
    "D1 Time Travel can still restore the database to a point before this purge "
    "for its retention window (7 days on the free plan).",
    "Earlier Pages deployments, and any snapshot.json in them, stay reachable at "
    "their deployment URLs until deleted in the Cloudflare dashboard.",
    "Cloudflare's own request logs are outside anything this tool can touch.",
)


@app.command("purge")
def purge_cmd(
    yes: bool = typer.Option(False, "--yes", help="Required. Purge never runs unattended."),
    skip_hosted: bool = typer.Option(
        False, "--skip-hosted", help="Purge this machine even if the hosted copy cannot be reached."
    ),
) -> None:
    """Delete the dossier and the hosted copy, then verify nothing recoverable remains."""
    from jobagent.companion import client as companion
    from jobagent.core.lifecycle import purge as run_purge

    data_dir = default_data_dir()
    try:
        hosted = companion.CompanionConfig.from_env()
    except companion.CompanionNotConfigured as exc:
        console.print(f"[red]Companion half-configured:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not yes:
        console.print(f"This deletes everything under [bold]{data_dir}[/bold]:")
        console.print("  profile, resume, jobs, application history, documents, audit log.")
        if hosted is not None:
            console.print(f"  and every row the hosted tracker at {hosted.url} holds.")
        console.print("Re-run with [bold]--yes[/bold] if that is what you want.")
        raise typer.Exit(code=1)

    # Hosted first. Once the local dossier is gone, nothing is left to remind
    # you that a copy exists elsewhere, so a failure here stops the purge.
    if hosted is not None:
        try:
            with companion.connect(hosted) as client:
                client.check_gate()
                result = client.purge()
        except (companion.AccessGateOff, companion.CompanionError, OSError) as exc:
            console.print(f"[red]Hosted copy not purged:[/red] {exc}")
            if not skip_hosted:
                console.print("Nothing was deleted. Fix that, or re-run with --skip-hosted.")
                raise typer.Exit(code=1) from exc
        else:
            if not result.get("clean"):
                console.print(f"[red]Hosted copy survived purge:[/red] {result.get('remaining')}")
                if not skip_hosted:
                    raise typer.Exit(code=1)
            else:
                removed = sum(result.get("removed", {}).values())
                console.print(
                    f"[green]Hosted tracker emptied[/green] ({removed} row(s)). Verified."
                )
            console.print("[yellow]Not reachable from here:[/yellow]")
            for limit in HOSTED_PURGE_LIMITS:
                console.print(f"  - {limit}")
    else:
        console.print("[dim]No hosted companion configured; purging this machine only.[/dim]")

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


def _select_adapters(source: str, company: str | None, workday_all: tuple[Any, ...]) -> list[Any]:
    """Which adapter(s) `source` names. Pure and network-free, so the parsing that
    decides what `jobagent fetch` is about to hit is testable on its own -- this is
    exactly the kind of branch that would otherwise fail silently: a typo routing
    to the wrong tenant, or an empty board slug reaching the network layer.

    Raises `ValueError` for a malformed `greenhouse:` source; returns an empty list
    for an unrecognized one, matching the pre-existing "no match" convention.
    """
    from jobagent.discovery.greenhouse import GreenhouseAdapter

    if source == "all":
        return list(workday_all)
    if source.startswith("greenhouse:"):
        board_slug = source.split(":", 1)[1]
        if not board_slug:
            raise ValueError(f"invalid greenhouse source {source!r}. Use: greenhouse:board-slug")
        return [GreenhouseAdapter(board=board_slug, company=company or board_slug.title())]
    return [a for a in workday_all if a.name == source]


@app.command()
def fetch(
    source: str = typer.Argument(
        ..., help="Adapter name: workday:rbc, greenhouse:acme, or 'all' for every tenant."
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Max postings to pull."),
    match: str = typer.Option(None, "--match", "-m", help="Only keep titles containing this text."),
    details: bool = typer.Option(
        False,
        "--details",
        help="Also fetch each posting's description and closing date. One extra "
        "request per posting, so it is slower.",
    ),
    company: str = typer.Option(
        None,
        "--company",
        help="Display name for company (greenhouse only; defaults to board slug title-cased).",
    ),
) -> None:
    """Pull postings from a source onto the board.

    Nothing is applied to; rows land as `new` for you to triage.
    """
    from jobagent.discovery.http import HostNotAllowed, PoliteClient, SourceDeclined
    from jobagent.discovery.workday import ALL as WORKDAY_ALL

    try:
        adapters = _select_adapters(source, company, WORKDAY_ALL)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    if not adapters:
        console.print(f"[red]Unknown source[/red] {source!r}.")
        workday_sources = ", ".join(a.name for a in WORKDAY_ALL)
        console.print(f"Known Workday sources: {workday_sources}, 'all', or greenhouse:board-slug.")
        raise typer.Exit(code=1)

    hosts = {h for a in adapters for h in a.hosts}
    added = skipped = deadlines_found = detail_failures = 0
    with Storage() as store, PoliteClient(hosts, min_interval_seconds=2.0) as client:
        repo = BoardRepo(store)
        # Rows added before M0003 have no dedupe key, so they would look new
        # again on the next fetch. Idempotent, and a no-op once it has run.
        repo.backfill_normalized()
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

            kept = [p for p in postings if not match or match.lower() in p.title.lower()]
            if details and kept:
                console.print(
                    f"[dim]Fetching {len(kept)} description(s) from {adapter.name}...[/dim]"
                )

            for posting in kept:
                if details:
                    posting, failed = _with_detail(adapter, client, posting)
                    detail_failures += failed
                repo.store_raw(posting.source, posting.source_id, posting.raw)
                _job, created = repo.add(
                    company=posting.company,
                    title=posting.title,
                    url=posting.url,
                    location=posting.location,
                    source=posting.source,
                    source_id=posting.source_id,
                    description=posting.description,
                    deadline=posting.deadline,
                )
                added += created
                skipped += not created
                deadlines_found += bool(posting.deadline)
            store.append_audit("fetch", {"source": adapter.name, "returned": len(postings)})

    console.print(f"[green]{added} new[/green], {skipped} already tracked (sighting recorded).")
    if deadlines_found:
        console.print(f"{deadlines_found} posting(s) carried a closing date.")
    if detail_failures:
        console.print(
            f"[yellow]{detail_failures} description(s) could not be fetched.[/yellow] "
            "The rows are on the board without them."
        )
    if added:
        console.print("Run [bold]jobagent board[/bold] to triage them.")


def _with_detail(
    adapter: object, client: PoliteClient, posting: RawPosting
) -> tuple[RawPosting, int]:
    """Fetch one posting's detail, tolerating failure.

    A tenant refusing the detail endpoint is a stop signal for the whole adapter
    and is re-raised. Anything else -- a shape we did not expect, one posting
    withdrawn between the list call and this one -- costs that description and
    nothing more. Losing the run over one bad posting would be worse than losing
    the field.

    If the adapter does not support detail fetching, returns the posting unchanged.
    """
    from jobagent.discovery.http import SourceDeclined

    # Only Workday adapters have fetch_detail; others don't fetch details separately
    if not hasattr(adapter, "fetch_detail"):
        return posting, 0

    try:
        return adapter.fetch_detail(client, posting), 0
    except SourceDeclined:
        raise
    except Exception:
        return posting, 1


@app.command()
def extract(
    job_id: int = typer.Argument(None, help="One job, or omit for every job with a description."),
    show: bool = typer.Option(False, "--show", help="Print what was extracted."),
) -> None:
    """Pull structured requirements out of stored posting text.

    Rule-based and free to run. Re-running is safe: extractions are appended, so
    the history of what each ruleset version found stays intact.
    """
    from jobagent.matching.extract import RULESET_VERSION
    from jobagent.matching.extract import extract as run_extract

    with Storage() as store:
        repo = BoardRepo(store)
        targets = repo.jobs_with_descriptions()
        if job_id is not None:
            targets = [(jid, text) for jid, text in targets if jid == job_id]
            if not targets:
                console.print(
                    f"[yellow]Job {job_id} has no stored description.[/yellow] "
                    "Run `jobagent fetch <source> --details` first."
                )
                raise typer.Exit(code=1)

        if not targets:
            console.print("[yellow]No postings have descriptions yet.[/yellow]")
            console.print("Run [bold]jobagent fetch <source> --details[/bold] to pull them.")
            return

        done = failed = 0
        for jid, text in targets:
            try:
                requirements = run_extract(text)
            except Exception as exc:  # one bad posting must not abort the run (#30)
                console.print(f"[yellow]Job {jid} could not be extracted:[/yellow] {exc}")
                failed += 1
                continue
            repo.save_requirements(jid, requirements)
            done += 1
            if show:
                job = repo.get(jid)
                console.print(
                    f"\n[bold]{job.company if job else jid} — {job.title if job else ''}[/bold]"
                )
                console.print(f"  required : {', '.join(requirements.required_skills) or '—'}")
                console.print(f"  preferred: {', '.join(requirements.preferred_skills) or '—'}")
                years = (
                    f"{requirements.min_years}-{requirements.max_years}"
                    if requirements.min_years is not None
                    else "—"
                )
                band = (
                    f"{requirements.compensation_min:,}-{requirements.compensation_max:,}"
                    f" {requirements.currency or ''}".strip()
                    if requirements.compensation_min is not None
                    else "not stated"
                )
                console.print(f"  years    : {years}    pay: {band}")
                console.print(
                    f"  closes   : {requirements.application_deadline or '—'}"
                    f"    arrangement: {requirements.work_arrangement or '—'}"
                )
        store.append_audit("extract", {"jobs": done, "ruleset": RULESET_VERSION})

    console.print(f"\n[green]Extracted {done}[/green] posting(s) with {RULESET_VERSION}.")
    if failed:
        console.print(f"[yellow]{failed} failed[/yellow] and were skipped.")


@app.command("score")
def score_cmd(
    filtered: bool = typer.Option(False, "--filtered", help="Show what the hard filters cut."),
    explain: int = typer.Option(None, "--explain", help="One job's full decomposition."),
) -> None:
    """Run the hard filters and score what survives (#31).

    Rule-based and free to run, so re-running after a `fetch` or an `extract` is
    the normal thing to do. Scores are appended rather than replaced: the
    history is what lets a later digest say a role's score moved.

    The ranked table here is deliberately plain. The daily digest -- thresholds,
    score movement, reposts, what the filters removed in aggregate -- is #32.
    """
    with Storage() as store:
        repo = BoardRepo(store)
        profile = _profile_or_exit(store)

        if not repo.scoring_rows():
            console.print("[yellow]Nothing on the board yet.[/yellow] Add or fetch a role first.")
            return
        _score_everything(repo, profile, store)

        latest = repo.latest_scores()
        cut = sum(1 for r in latest.values() if r["filtered"])

        if explain is not None:
            _explain_score(repo, latest, explain)
            return
        if filtered:
            _print_filtered(repo)
            return
        _print_ranking(repo, latest, cut)


def _print_ranking(repo: BoardRepo, latest: dict[int, Any], cut: int) -> None:
    ranked = sorted(
        ((jid, rec) for jid, rec in latest.items() if not rec["filtered"]),
        key=lambda pair: pair[1]["total"],
        reverse=True,
    )
    if not ranked:
        console.print(f"[yellow]Every row was cut by a hard filter[/yellow] ({cut}).")
        console.print("Run [bold]jobagent score --filtered[/bold] to see which rule, and why.")
        return

    table = Table(title=f"Ranked ({len(ranked)} scored, {cut} filtered out)")
    table.add_column("#", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Company")
    table.add_column("Title")
    table.add_column("Scored on", style="dim")

    for position, (job_id, record) in enumerate(ranked, start=1):
        job = repo.get(job_id)
        if job is None:
            continue
        components = record["components"]
        table.add_row(
            str(position),
            f"{record['total']:.2f}",
            job.company,
            job.title[:46],
            f"{len(components['scored_on'])}/5 components",
        )
    console.print(table)
    console.print("\n[dim]jobagent score --explain <job-id> for one row's decomposition.[/dim]")


def _print_filtered(repo: BoardRepo) -> None:
    rows = repo.filtered_jobs()
    if not rows:
        console.print("[green]Nothing was cut by a hard filter.[/green]")
        return
    table = Table(title=f"Filtered out ({len(rows)})")
    table.add_column("Company")
    table.add_column("Title")
    table.add_column("Why it was cut")
    for job, reason in rows:
        table.add_row(job.company, job.title[:40], reason)
    console.print(table)


def _explain_score(repo: BoardRepo, latest: dict[int, Any], job_id: int) -> None:
    record = latest.get(job_id)
    job = repo.get(job_id)
    if record is None or job is None:
        console.print(f"[yellow]No score for job {job_id}.[/yellow]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold]{job.company} — {job.title}[/bold]")
    if record["filtered"]:
        console.print(f"[red]Cut by a hard filter:[/red] {record['filter_reason']}")

    payload = record["components"]
    # The components below are the real ones -- a cut job is still scored, so
    # that "would this have ranked well if the filter were wrong?" is answerable.
    # The stored total is 0 because it is out of the ranking, and the title has
    # to say which of the two numbers it is showing.
    heading = (
        f"Score {payload['total']:.2f} — not ranked, cut before scoring counted"
        if record["filtered"]
        else f"Score {payload['total']:.2f}"
    )
    table = Table(title=heading)
    table.add_column("Component")
    table.add_column("Value", justify="right")
    table.add_column("Weight", justify="right")
    table.add_column("Basis", style="dim")
    for name, component in payload["components"].items():
        value = "—" if component["value"] is None else f"{component['value']:.2f}"
        weight = f"{component['weight']:.2f}" if component["value"] is not None else "—"
        table.add_row(name, value, weight, component["basis"])
    console.print(table)
    if payload["unavailable"]:
        console.print(
            f"[dim]Scored on {len(payload['scored_on'])} of 5 components; "
            f"{', '.join(payload['unavailable'])} had nothing to judge on, so the "
            "remaining weights were rescaled.[/dim]"
        )


@app.command("import")
def import_shortlist(
    path: Path = typer.Argument(..., help="A shortlist YAML. See shortlist.example.yaml."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would change and write nothing."
    ),
) -> None:
    """Put a triaged shortlist on the board, judgements and all.

    The fit score and reasoning land in each row's notes, attributed to their
    source and dated -- they are somebody else's opinion, not this tool's, and
    they never feed `jobagent score`.
    """
    from jobagent.tracking.leads import apply_to_board
    from jobagent.tracking.leads import load_file as load_shortlist

    try:
        shortlist = load_shortlist(path)
    except FileNotFoundError:
        console.print(f"[red]No shortlist at[/red] {path}")
        console.print(
            "Start from the example: [bold]cp shortlist.example.yaml[/bold] ~/shortlist.yaml"
        )
        raise typer.Exit(code=1) from None
    except Exception as exc:  # pydantic and yaml both name the offending field
        console.print(f"[red]Invalid shortlist[/red] at {path}:\n{exc}")
        console.print("[dim]Nothing was written.[/dim]")
        raise typer.Exit(code=1) from None

    with Storage() as store:
        repo = BoardRepo(store)
        result = apply_to_board(repo, shortlist, dry_run=dry_run)
        if not dry_run:
            store.append_audit(
                "shortlist.import",
                {
                    "source": shortlist.source,
                    "retrieved": shortlist.retrieved,
                    "leads": len(shortlist.leads),
                    "added": result.added,
                },
            )

    table = Table(title=f"{shortlist.source} — {shortlist.retrieved}")
    table.add_column("Company")
    table.add_column("Role")
    table.add_column("Action")
    table.add_column("Note")
    for outcome in result.outcomes:
        colour = {"added": "green", "left alone": "yellow"}.get(outcome.action, "")
        action = f"[{colour}]{outcome.action}[/]" if colour else outcome.action
        table.add_row(outcome.company, outcome.title[:44], action, outcome.detail)
    console.print(table)

    if dry_run:
        console.print("[yellow]Dry run — nothing was written.[/yellow]")
        return
    console.print(
        f"[green]{result.added} added[/green], {result.updated} updated, "
        f"{result.left_alone} left alone."
    )
    if result.left_alone:
        console.print(
            "[dim]Rows you have already applied to or heard back from are never "
            "moved by an import.[/dim]"
        )


def _profile_or_exit(store: Storage) -> Profile:
    profile = load_stored_profile(store)
    if profile is None:
        console.print("[yellow]No profile set.[/yellow] Every filter and weight reads it.")
        console.print("Run [bold]jobagent profile set <file.yaml>[/bold] first.")
        raise typer.Exit(code=1)
    return profile


def _score_everything(repo: BoardRepo, profile: Profile, store: Storage) -> int:
    """Filter and score every row. Shared by `score` and `daily`."""
    from jobagent.matching.filters import apply_filters
    from jobagent.matching.score import score as run_score

    rows = repo.scoring_rows()
    for job_id, listing, posted_at in rows:
        stored = repo.latest_requirements(job_id)
        requirements = Requirements() if stored is None else Requirements.from_dict(stored)
        verdict = apply_filters(listing, requirements, profile)
        result = run_score(listing, requirements, profile, posted_at, extracted=stored is not None)
        repo.save_score(job_id, result, verdict)
    cut = sum(1 for r in repo.latest_scores().values() if r["filtered"])
    store.append_audit("score", {"jobs": len(rows), "filtered": cut})
    return len(rows)


@app.command()
def shortlist(
    min_score: float = typer.Option(None, "--min-score", help="Override the profile's threshold."),
    company: str = typer.Option(None, "--company", "-c", help="Only this employer."),
    source: str = typer.Option(None, "--source", "-s", help="Only rows seen from this source."),
    since_days: int = typer.Option(
        None, "--since-days", help="Only rows first seen this recently."
    ),
    snoozed: bool = typer.Option(False, "--snoozed", help="Include snoozed rows."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
) -> None:
    """The ranked list of what is worth an evening (#32).

    Rows the hard filters cut are not here -- they were already judged, and
    `jobagent score --filtered` is where those live with their reason.
    """
    from jobagent.tracking.shortlist import Filters
    from jobagent.tracking.shortlist import build as build_shortlist

    with Storage() as store:
        repo = BoardRepo(store)
        profile = _profile_or_exit(store)
        entries = build_shortlist(
            repo.all(),
            repo.latest_scores(),
            repo.sighting_counts(),
            profile,
            Filters(
                min_score=min_score,
                company=company,
                source=source,
                since_days=since_days,
                include_snoozed=snoozed,
            ),
            sources=repo.sources_by_job() if source else None,
        )

    threshold = min_score if min_score is not None else profile.shortlist.min_score
    if as_json:
        console.print_json(data={"min_score": threshold, "entries": [e.as_dict() for e in entries]})
        return

    if not entries:
        console.print(f"[yellow]Nothing at or above {threshold:.2f}.[/yellow]")
        console.print(
            "Lower it with [bold]--min-score[/bold], or check "
            "[bold]jobagent score --filtered[/bold] for what was cut."
        )
        return
    _print_entries(entries, title=f"Shortlist — {len(entries)} at or above {threshold:.2f}")


def _print_entries(entries: list[Any], title: str) -> None:
    table = Table(title=title)
    table.add_column("#", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Company")
    table.add_column("Title")
    table.add_column("Closes")
    table.add_column("Basis", style="dim")
    for position, entry in enumerate(entries, start=1):
        flag = f" [magenta]×{entry.sightings}[/magenta]" if entry.is_repost else ""
        table.add_row(
            str(position),
            f"{entry.total:.2f}",
            entry.job.company,
            entry.job.title[:44] + flag,
            entry.job.deadline or "—",
            f"{len(entry.scored_on)}/5 components",
        )
    console.print(table)


@app.command()
def digest(
    since: int = typer.Option(1, "--since", help="Fallback window when no digest has run."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    no_record: bool = typer.Option(False, "--no-record", help="Build digest without recording."),
) -> None:
    """The reading queue: new, moved, reposted, and what the filters ate (#32).

    Meant for ten minutes over coffee, so every section is capped. Running it
    records that you looked, which is what makes the next run's "new" mean
    "since you last read this" rather than "in the last day".
    """
    from jobagent.tracking.digest import build as build_digest

    with Storage() as store:
        repo = BoardRepo(store)
        profile = _profile_or_exit(store)
        result = build_digest(
            repo.all(),
            repo.latest_scores(),
            repo.sighting_counts(),
            repo.score_movement(),
            repo.filtered_jobs(),
            profile,
            last_run=store.last_audit("digest"),
            fallback_days=since,
        )
        if not no_record:
            store.append_audit("digest", {"new": len(result.new), "moved": len(result.moved)})

    if as_json:
        console.print_json(data=result.as_dict())
        return
    _render_digest(result)


def _render_digest(result: Any) -> None:
    console.print(
        f"\n[bold]Digest[/bold] [dim]— new since {result.since} ({result.since_source})[/dim]"
    )

    if result.is_empty:
        console.print("\n[green]Nothing new worth reading.[/green]")
    if result.new:
        _print_entries(result.new, title=f"New ({len(result.new)})")
    if result.moved:
        table = Table(title=f"Score moved ({len(result.moved)})")
        table.add_column("Company")
        table.add_column("Title")
        table.add_column("Was", justify="right")
        table.add_column("Now", justify="right")
        table.add_column("What changed", style="dim")
        for m in result.moved:
            arrow = "[green]▲[/green]" if m.delta > 0 else "[red]▼[/red]"
            why = ", ".join(m.changed) or "weights rescaled, no component changed"
            if m.dropped_off:
                why = f"[yellow]fell below your threshold[/yellow] — {why}"
            table.add_row(
                m.entry.job.company,
                m.entry.job.title[:38],
                f"{m.previous:.2f}",
                f"{arrow} {m.latest:.2f}",
                why,
            )
        console.print(table)
    if result.reposts:
        table = Table(title=f"Seen before ({len(result.reposts)})")
        table.add_column("Company")
        table.add_column("Title")
        table.add_column("Times seen", justify="right")
        for entry in result.reposts:
            table.add_row(entry.job.company, entry.job.title[:44], str(entry.sightings))
        console.print(table)
        console.print(
            "[dim]A role reposted repeatedly is either hard to fill or a phantom. "
            "Worth knowing before an evening on a cover letter.[/dim]"
        )
    if result.total_filtered:
        summary = ", ".join(f"{count} by {rule}" for rule, count in result.filtered.items())
        console.print(f"\n[dim]Hard filters cut {result.total_filtered}: {summary}.[/dim]")
        console.print("[dim]jobagent score --filtered to see which, and why.[/dim]")


@app.command()
def skip(
    job_id: int = typer.Argument(..., help="The row to skip."),
    reason: str = typer.Option(..., "--reason", "-r", help="Why. Stored, and read by `report`."),
) -> None:
    """Skip a role, recording why.

    The reason is the point: three weeks from now a skip with no reason is
    indistinguishable from one you would reverse today.
    """
    with Storage() as store:
        repo = BoardRepo(store)
        job = repo.get(job_id)
        if job is None:
            console.print(f"[yellow]No job {job_id}.[/yellow]")
            raise typer.Exit(code=1)
        repo.set_state(job_id, State.SKIPPED, reason=reason)
    console.print(f"[dim]○[/dim] Skipped: {job.company} — {job.title}")
    console.print(f"  [dim]{reason}[/dim]")


@app.command()
def snooze(
    job_id: int = typer.Argument(..., help="The row to hide for a while."),
    days: int = typer.Option(7, "--days", "-d", help="How long to hide it."),
) -> None:
    """Hide a role from the digest until a date, without deciding anything.

    Deliberately not a state. "Not now" is not a decision, and making it one
    means remembering to undo it.
    """
    from datetime import timedelta

    if days < 1:
        console.print("[yellow]--days must be at least 1.[/yellow]")
        raise typer.Exit(code=1)
    until = date.today() + timedelta(days=days)
    with Storage() as store:
        repo = BoardRepo(store)
        job = repo.get(job_id)
        if job is None:
            console.print(f"[yellow]No job {job_id}.[/yellow]")
            raise typer.Exit(code=1)
        repo.snooze(job_id, until)
    console.print(f"[dim]💤 {job.company} — {job.title}[/dim]")
    console.print(f"  back on {until.isoformat()}")


@app.command()
def daily(
    source: list[str] = typer.Option(
        None, "--source", "-s", help="Fetch this source first. Repeatable. Omit to skip fetching."
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Max postings per source."),
) -> None:
    """The unattended run: fetch, extract, score, then print the digest (#32).

    Safe for cron. Fetching happens only for sources named explicitly -- a
    default that silently hits live bank tenants every morning is the wrong
    default, and the adapters treat a 401/403 as a refusal rather than a puzzle.
    """
    from jobagent.matching.extract import RULESET_VERSION
    from jobagent.matching.extract import extract as run_extract

    # One bad source must not cost the run its digest. Failures are collected
    # and reported at the end as a non-zero exit, so cron still gets the reading
    # queue AND something to alert on -- aborting here would throw away the
    # extract and score passes over everything already on the board.
    failures: list[str] = []
    for name in source or []:
        console.print(f"[dim]fetching {name}…[/dim]")
        try:
            fetch(name, limit=limit, match="", details=True)
        except typer.Exit as exc:
            if exc.exit_code:
                failures.append(f"{name} (unknown adapter, or nothing fetched)")
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            console.print(f"[yellow]{name} failed:[/yellow] {exc}")

    with Storage() as store:
        repo = BoardRepo(store)
        profile = _profile_or_exit(store)

        extracted = 0
        for job_id, text in repo.jobs_with_descriptions():
            try:
                repo.save_requirements(job_id, run_extract(text))
                extracted += 1
            except Exception as exc:
                console.print(f"[yellow]job {job_id} could not be extracted:[/yellow] {exc}")
        store.append_audit("extract", {"jobs": extracted, "ruleset": RULESET_VERSION})
        scored = _score_everything(repo, profile, store)

    console.print(f"[dim]extracted {extracted}, scored {scored}[/dim]")
    # An unattended run counting as the owner reading the digest breaks "new since you
    # last looked" silently. No record means the digest is printed and logged but does
    # not reset the baseline for the next human run.
    digest(since=1, as_json=False, no_record=True)

    if failures:
        console.print(f"\n[yellow]{len(failures)} source(s) failed:[/yellow] {'; '.join(failures)}")
        raise typer.Exit(code=1)


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

    if data.skip_reasons or data.skipped_without_reason:
        reasons = Table(title="Why roles were skipped")
        reasons.add_column("Reason")
        reasons.add_column("Count", justify="right")
        for reason, count in data.skip_reasons[:10]:
            reasons.add_row(reason, str(count))
        if data.skipped_without_reason:
            reasons.add_row("[dim]no reason recorded[/dim]", str(data.skipped_without_reason))
        console.print(reasons)
        if data.skipped_without_reason and not data.skip_reasons:
            console.print(
                '[dim]Nothing here says why. `jobagent skip <id> -r "..."` records a reason; '
                "the board's `s` key does not ask for one.[/dim]"
            )

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


@app.command()
def snapshot(
    destination: Path = typer.Argument(
        ..., help="File to write the snapshot JSON into, e.g. cloudflare/public/snapshot.json"
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Print to stdout instead of writing a file."
    ),
) -> None:
    """Write the phone snapshot: the only board fields allowed off this machine.

    Builds the file. Does not upload it -- pushing is a separate, deliberate act
    by a human, and nothing in this tool reaches Cloudflare on its own.
    """
    import json
    from datetime import UTC, datetime

    from jobagent.tracking.snapshot import build as build_snapshot

    with Storage() as store:
        payload = build_snapshot(BoardRepo(store).all(), generated_at=datetime.now(UTC)).as_dict()

    if as_json:
        console.print_json(data=payload)
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    destination.chmod(0o600)
    console.print(f"[green]Wrote[/green] {destination} ({len(payload['rows'])} rows)")
    console.print(
        "[yellow]This names every company on your board and where each one stands.[/yellow] "
        "It belongs behind the Cloudflare Access login -- see docs/adr/0009."
    )


@app.command("sync")
def sync_cmd(
    yes: bool = typer.Option(
        False, "--yes", help="Send. Without it, show the plan and send nothing."
    ),
    check: bool = typer.Option(False, "--check", help="Only confirm the Access gate is on."),
) -> None:
    """Reconcile the board with the hosted tracker (ADR 0010). Never runs unattended.

    Sends only the fields in `jobagent.companion.contract`, and takes back only
    status changes made on the phone. Refuses outright if the companion answers
    without a Cloudflare Access login. Not part of `daily`, on purpose.
    """
    from jobagent.companion import client as companion
    from jobagent.companion.contract import FROM_BOARD, HOSTED_ONLY
    from jobagent.companion.state import SyncStateRepo
    from jobagent.companion.sync import plan as plan_sync
    from jobagent.companion.sync import run as run_sync

    config = _companion_config_or_exit(companion)
    try:
        with companion.connect(config) as client:
            client.check_gate()
            console.print(f"[green]Access gate is on[/green] for {config.url}.")
            if check:
                return
            hosted = client.pull()
            with Storage() as store:
                repo, state = BoardRepo(store), SyncStateRepo(store)
                jobs = repo.all()
                the_plan = plan_sync(jobs, hosted, state.all())
                names = {job.id: f"{job.company} — {job.title}" for job in jobs}

                console.print(
                    f"To send: {len(the_plan.pushes)} row(s), carrying only "
                    f"{', '.join([*FROM_BOARD, *HOSTED_ONLY])}. "
                    f"To remove: {len(the_plan.removals)}. From the phone: {len(the_plan.pulls)}."
                )
                for pull in the_plan.pulls:
                    job = repo.get(pull.job_id)
                    console.print(
                        f"  ← {names.get(pull.job_id)}: {job.state if job else '?'} → {pull.status}"
                    )
                for conflict in the_plan.conflicts:
                    console.print(
                        f"  [yellow]conflict[/yellow] {names.get(conflict.job_id)}: board says "
                        f"{conflict.board_status}, phone says {conflict.hosted_status}. Left alone."
                    )
                if not yes:
                    console.print("Dry run: nothing sent. Re-run with [bold]--yes[/bold] to send.")
                    return
                if the_plan.empty:
                    console.print("Already in agreement.")
                    if the_plan.conflicts:
                        raise typer.Exit(code=1)
                    return

                outcome = run_sync(
                    client,
                    the_plan,
                    set_state=lambda job_id, new_state: repo.set_state(job_id, new_state),
                    record=state.record,
                    forget=state.forget,
                )
                # Counts only: a company name in the audit detail is the thing
                # most likely to be pasted somewhere while debugging.
                store.append_audit(
                    "companion.sync",
                    {
                        "pushed": outcome.pushed,
                        "pulled": outcome.pulled,
                        "removed": outcome.removed,
                        "conflicts": len(outcome.conflicts),
                    },
                )
    except (companion.AccessGateOff, companion.CompanionError) as exc:
        console.print(f"[red]Not synced:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]Synced.[/green] Sent {outcome.pushed}, took {outcome.pulled} from the phone, "
        f"removed {outcome.removed}."
    )
    if outcome.conflicts:
        console.print(f"[yellow]{len(outcome.conflicts)} conflict(s) left for you.[/yellow]")
        raise typer.Exit(code=1)


def _companion_config_or_exit(companion: Any) -> Any:
    try:
        config = companion.CompanionConfig.from_env()
    except companion.CompanionNotConfigured as exc:
        console.print(f"[red]Companion half-configured:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if config is None:
        console.print(
            "No hosted companion configured. Set JOBAGENT_COMPANION_URL, JOBAGENT_SYNC_TOKEN, "
            "JOBAGENT_ACCESS_CLIENT_ID and JOBAGENT_ACCESS_CLIENT_SECRET (cloudflare/README.md)."
        )
        raise typer.Exit(code=1)
    return config


if __name__ == "__main__":
    app()
