"""Typer CLI for the synthetic data pipeline.

Examples:
    python -m data_generator.cli generate                   # write CSVs to ./data/raw
    python -m data_generator.cli generate --days 30 --seed 7
    python -m data_generator.cli load                       # load latest CSVs into Postgres
    python -m data_generator.cli seed                       # generate + load in one shot
    python -m data_generator.cli summary                    # print row counts and break stats
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import load_settings
from .loader import load_csv_dir, load_dataframes
from .logging_setup import configure_logging
from .pipeline import run_pipeline

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
console = Console()


def _persist_csvs(tables: dict, breaks_log, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(output_dir / f"{name.replace('.', '__')}.csv", index=False)
    breaks_log.to_csv(output_dir / "_breaks_log.csv", index=False)


def _render_counts(title: str, counts: dict[str, int]) -> None:
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("Table")
    table.add_column("Rows", justify="right")
    for k, v in counts.items():
        table.add_row(k, f"{v:,}")
    console.print(table)


@app.command()
def generate(
    days: int | None = typer.Option(None, help="Override GLRECON_DAYS"),
    seed: int | None = typer.Option(None, help="Override GLRECON_SEED"),
    output_dir: Path | None = typer.Option(None, help="Override output directory"),
    log_level: str = typer.Option("INFO", help="DEBUG | INFO | WARNING | ERROR"),
) -> None:
    """Generate synthetic AP/AR/Inventory/GL data and write CSVs to disk."""
    configure_logging(log_level)
    overrides: dict = {}
    if days is not None:
        overrides["days"] = days
    if seed is not None:
        overrides["seed"] = seed
    if output_dir is not None:
        overrides["output_dir"] = output_dir
    settings = load_settings(**overrides)

    dataset = run_pipeline(settings)
    _persist_csvs(dataset.tables, dataset.breaks_log, settings.output_dir)

    _render_counts("Generated row counts", dataset.row_counts())
    if len(dataset.breaks_log):
        _render_counts(
            "Injected breaks by class",
            dataset.breaks_log["break_class"].value_counts().to_dict(),
        )
    console.print(f"[green]CSVs written to[/green] {settings.output_dir}")


@app.command()
def load(
    output_dir: Path | None = typer.Option(None, help="Directory to load CSVs from"),
    log_level: str = typer.Option("INFO"),
) -> None:
    """Load the most recently generated CSVs into Postgres bronze tables."""
    configure_logging(log_level)
    overrides = {"output_dir": output_dir} if output_dir is not None else {}
    settings = load_settings(**overrides)
    counts = load_csv_dir(settings, settings.output_dir)
    _render_counts("Loaded into Postgres", counts)


@app.command()
def seed(
    days: int | None = typer.Option(None),
    seed_value: int | None = typer.Option(None, "--seed"),
    log_level: str = typer.Option("INFO"),
) -> None:
    """Generate + load in one shot (skips writing CSVs to disk)."""
    configure_logging(log_level)
    overrides: dict = {}
    if days is not None:
        overrides["days"] = days
    if seed_value is not None:
        overrides["seed"] = seed_value
    settings = load_settings(**overrides)
    dataset = run_pipeline(settings)
    counts = load_dataframes(settings, dataset.tables)
    _render_counts("Loaded into Postgres", counts)
    if len(dataset.breaks_log):
        _render_counts(
            "Injected breaks by class",
            dataset.breaks_log["break_class"].value_counts().to_dict(),
        )


@app.command()
def summary() -> None:
    """Print row counts in the raw schema. Sanity check after load."""
    from sqlalchemy import create_engine, text
    settings = load_settings()
    engine = create_engine(settings.postgres_dsn, future=True)
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'raw' ORDER BY table_name
        """)).fetchall()
        for (t,) in rows:
            n = conn.execute(text(f"SELECT count(*) FROM raw.{t}")).scalar_one()
            counts[f"raw.{t}"] = int(n)
    _render_counts("Postgres raw.* row counts", counts)


if __name__ == "__main__":
    app()
