"""CLI entry point.

The full command surface lands in #26 (Day 2). Day 1 ships only what proves the
foundation works: initialise the data directory, show status, read the audit log.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from jobagent.core.paths import default_data_dir, ensure_data_dir
from jobagent.core.pii import REGISTRY
from jobagent.core.storage import Storage

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


if __name__ == "__main__":
    app()
