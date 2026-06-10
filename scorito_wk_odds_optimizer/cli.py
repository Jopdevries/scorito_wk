from __future__ import annotations

import asyncio
import os
import shutil
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

import typer
from pydantic import BaseModel, ValidationError
from rich.console import Console

from .exporter import export_all, write_csv
from .group_standings import compute_group_standings
from .logging_utils import configure_logging, load_json, save_json
from .manual_loader import ManualData, load_manual_data
from .market_aggregation import (
    aggregate_1x2,
    aggregate_correct_score,
    aggregate_ou_btts,
    aggregate_outrights,
    aggregate_topscorers,
)
from .match_optimizer import optimize_matches
from .outright_optimizer import optimize_outrights
from .player_metadata import resolve_player_metadata
from .quality_gate import run_quality_gate
from .rules import ScoritoRules, load_rules, print_rules_table
from .schemas import (
    AggregatedMarketProbability,
    Fixture,
    PlayerMetadata,
    Raw1X2Odd,
    RawCorrectScoreOdd,
    RawOUBTTSOdd,
    RawOutrightOdd,
    RawTopGoalscorerOdd,
)
from .source_apifootball import fetch_api_football_metadata
from .source_oddschecker import OddscheckerScraper
from .source_oddsportal import OddsPortalScraper
from .source_theoddsapi import fetch_the_odds_api
from .topscorer_optimizer import optimize_topscorers

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()
T = TypeVar("T", bound=BaseModel)


@dataclass
class PipelineData:
    fixtures: list[Fixture] = field(default_factory=list)
    x1x2: list[Raw1X2Odd] = field(default_factory=list)
    correct_scores: list[RawCorrectScoreOdd] = field(default_factory=list)
    ou_btts: list[RawOUBTTSOdd] = field(default_factory=list)
    outrights: list[RawOutrightOdd] = field(default_factory=list)
    topscorers: list[RawTopGoalscorerOdd] = field(default_factory=list)
    api_metadata: list[PlayerMetadata] = field(default_factory=list)
    manual_metadata: list[PlayerMetadata] = field(default_factory=list)
    validation_errors: list[dict[str, str]] = field(default_factory=list)
    source_failures: list[str] = field(default_factory=list)


@app.command("print-rules")
def print_rules(
    rules: Path = typer.Option(Path("config/scorito_rules.yaml"), "--rules"),
) -> None:
    print_rules_table(load_rules(rules), console)


@app.command("scrape-oddsportal")
def scrape_oddsportal(
    headless: str = typer.Option("true", "--headless"),
    max_matches: int | None = typer.Option(None, "--max-matches", min=1),
) -> None:
    configure_logging()
    asyncio.run(
        OddsPortalScraper(headless=_parse_bool(headless, "--headless")).scrape_all(
            max_matches
        )
    )


@app.command("scrape-oddschecker")
def scrape_oddschecker(
    headless: str = typer.Option("true", "--headless"),
) -> None:
    configure_logging()
    headless_value = _parse_bool(headless, "--headless")

    async def run() -> None:
        scraper = OddscheckerScraper(headless=headless_value)
        await scraper.scrape_winner_odds()
        await scraper.scrape_top_goalscorer_odds()

    asyncio.run(run())


@app.command("import-oddschecker-html")
def import_oddschecker_html(
    winner: Path = typer.Option(
        Path("input/oddschecker_winner.html"),
        "--winner",
    ),
    topscorer: Path = typer.Option(
        Path("input/oddschecker_top_goalscorer.html"),
        "--topscorer",
    ),
) -> None:
    configure_logging()

    if not winner.is_file() and not topscorer.is_file():
        raise typer.BadParameter(
            "No saved Oddschecker HTML files found. Expected "
            f"{winner} and/or {topscorer}."
        )

    async def run() -> tuple[int | None, int | None]:
        scraper = OddscheckerScraper(headless=True)
        winner_count = None
        topscorer_count = None
        if winner.is_file():
            winner_rows = await scraper.import_saved_winner_html(winner)
            winner_count = len(winner_rows)
        if topscorer.is_file():
            topscorer_rows = await scraper.import_saved_top_goalscorer_html(
                topscorer
            )
            topscorer_count = len(topscorer_rows)
        return winner_count, topscorer_count

    winner_count, topscorer_count = asyncio.run(run())
    imported = []
    skipped = []
    if winner_count is not None:
        imported.append(f"{winner_count} winner odds rows")
    else:
        skipped.append(str(winner))
    if topscorer_count is not None:
        imported.append(f"{topscorer_count} top-goalscorer odds rows")
    else:
        skipped.append(str(topscorer))
    console.print(f"Imported {' and '.join(imported)}.")
    if skipped:
        console.print(
            "[yellow]Skipped missing optional file(s): "
            f"{', '.join(skipped)}.[/yellow]"
        )


@app.command("fetch-theoddsapi")
def fetch_theoddsapi_command() -> None:
    configure_logging()
    data = fetch_the_odds_api()
    console.print(
        f"Fetched {len(data['fixtures'])} fixtures from The Odds API."
    )


@app.command("fetch-apifootball")
def fetch_apifootball_command(
    force_retry: bool = typer.Option(False, "--force-retry"),
) -> None:
    configure_logging()
    data = _collect_data("mixed", use_manual_fallback=True)
    players = _top_player_country_pairs(data.topscorers)
    metadata = fetch_api_football_metadata(
        players,
        force_retry=force_retry,
    )
    console.print(
        f"Available validated metadata for {len(metadata)} of "
        f"{len(players)} top-goalscorer players."
    )


@app.command("load-manual")
def load_manual_command(
    prefer_source: str = typer.Option("mixed", "--prefer-source"),
) -> None:
    _validate_prefer_source(prefer_source)
    manual = load_manual_data()
    save_json("data/raw/manual/parsed.json", _manual_to_dict(manual))
    console.print(
        f"Loaded {len(manual.fixtures)} fixtures, {len(manual.x1x2)} 1X2 rows, "
        f"{len(manual.correct_scores)} correct-score rows and "
        f"{len(manual.errors)} validation errors."
    )


@app.command("optimize-matches")
def optimize_matches_command(
    rules: Path = typer.Option(Path("config/scorito_rules.yaml"), "--rules"),
    output_dir: Path = typer.Option(Path("output"), "--output-dir"),
    prefer_source: str = typer.Option("mixed", "--prefer-source"),
    use_manual_fallback: str = typer.Option("true", "--use-manual-fallback"),
) -> None:
    result = _run_processing(
        rules,
        output_dir,
        prefer_source,
        _parse_bool(use_manual_fallback, "--use-manual-fallback"),
    )
    console.print(f"Created {len(result['predictions'])} match predictions.")


@app.command("optimize-outrights")
def optimize_outrights_command(
    rules: Path = typer.Option(Path("config/scorito_rules.yaml"), "--rules"),
    output_dir: Path = typer.Option(Path("output"), "--output-dir"),
    prefer_source: str = typer.Option("mixed", "--prefer-source"),
    use_manual_fallback: str = typer.Option("true", "--use-manual-fallback"),
) -> None:
    result = _run_processing(
        rules,
        output_dir,
        prefer_source,
        _parse_bool(use_manual_fallback, "--use-manual-fallback"),
    )
    console.print(f"Created {len(result['outrights'])} outright recommendations.")


@app.command("optimize-topscorers")
def optimize_topscorers_command(
    rules: Path = typer.Option(Path("config/scorito_rules.yaml"), "--rules"),
    output_dir: Path = typer.Option(Path("output"), "--output-dir"),
    prefer_source: str = typer.Option("mixed", "--prefer-source"),
    use_manual_fallback: str = typer.Option("true", "--use-manual-fallback"),
) -> None:
    result = _run_processing(
        rules,
        output_dir,
        prefer_source,
        _parse_bool(use_manual_fallback, "--use-manual-fallback"),
    )
    console.print(
        f"Created {len(result['topscorers'])} topscorer recommendations."
    )


@app.command("compute-group-standings")
def compute_group_standings_command(
    rules: Path = typer.Option(Path("config/scorito_rules.yaml"), "--rules"),
    output_dir: Path = typer.Option(Path("output"), "--output-dir"),
    prefer_source: str = typer.Option("mixed", "--prefer-source"),
    use_manual_fallback: str = typer.Option("true", "--use-manual-fallback"),
) -> None:
    result = _run_processing(
        rules,
        output_dir,
        prefer_source,
        _parse_bool(use_manual_fallback, "--use-manual-fallback"),
    )
    console.print(f"Created {len(result['rankings'])} group-ranking rows.")


@app.command("export-summary")
def export_summary_command(
    rules: Path = typer.Option(Path("config/scorito_rules.yaml"), "--rules"),
    output_dir: Path = typer.Option(Path("output"), "--output-dir"),
    prefer_source: str = typer.Option("mixed", "--prefer-source"),
    use_manual_fallback: str = typer.Option("true", "--use-manual-fallback"),
) -> None:
    _run_processing(
        rules,
        output_dir,
        prefer_source,
        _parse_bool(use_manual_fallback, "--use-manual-fallback"),
    )
    console.print(f"Exported summary to {output_dir / 'summary.md'}.")


@app.command("run-all")
def run_all(
    headless: str = typer.Option("true", "--headless"),
    max_matches: int | None = typer.Option(None, "--max-matches", min=1),
    rules: Path = typer.Option(Path("config/scorito_rules.yaml"), "--rules"),
    output_dir: Path = typer.Option(Path("output"), "--output-dir"),
    prefer_source: str = typer.Option("mixed", "--prefer-source"),
    use_manual_fallback: str = typer.Option("true", "--use-manual-fallback"),
) -> None:
    configure_logging()
    _validate_prefer_source(prefer_source)
    headless_value = _parse_bool(headless, "--headless")
    manual_value = _parse_bool(use_manual_fallback, "--use-manual-fallback")
    _refresh_sources(headless_value, max_matches)
    data = _collect_data(prefer_source, manual_value)
    if data.topscorers:
        metadata = fetch_api_football_metadata(
            _top_player_country_pairs(data.topscorers)
        )
        if metadata:
            data.api_metadata = metadata
    _run_processing(
        rules,
        output_dir,
        prefer_source,
        manual_value,
        data=data,
    )
    console.print(f"Pipeline complete. Outputs: {output_dir.resolve()}")


@app.command("final-update")
def final_update(
    headless: str = typer.Option("true", "--headless"),
    max_matches: int | None = typer.Option(None, "--max-matches", min=1),
    rules: Path = typer.Option(Path("config/scorito_rules.yaml"), "--rules"),
    output_dir: Path = typer.Option(Path("output"), "--output-dir"),
    prefer_source: str = typer.Option("mixed", "--prefer-source"),
    use_manual_fallback: str = typer.Option("true", "--use-manual-fallback"),
) -> None:
    configure_logging()
    _validate_prefer_source(prefer_source)
    headless_value = _parse_bool(headless, "--headless")
    manual_value = _parse_bool(use_manual_fallback, "--use-manual-fallback")
    processed = Path("data/processed").resolve()
    workspace = Path.cwd().resolve()
    if processed.parent == workspace / "data" and processed.exists():
        _remove_tree_best_effort(processed)
    processed.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone()
    final_dir = output_dir / f"final_run_{timestamp:%Y%m%d_%H%M}"
    _refresh_sources(headless_value, max_matches, ignore_cache=True)
    data = _collect_data(prefer_source, manual_value)
    if data.topscorers:
        metadata = fetch_api_football_metadata(
            _top_player_country_pairs(data.topscorers)
        )
        if metadata:
            data.api_metadata = metadata
    _run_processing(
        rules,
        final_dir,
        prefer_source,
        manual_value,
        data=data,
        timestamp=timestamp,
    )
    console.print(f"Final update complete. Outputs: {final_dir.resolve()}")


def _refresh_sources(
    headless: bool,
    max_matches: int | None,
    ignore_cache: bool = False,
) -> None:
    if ignore_cache:
        for path in (
            Path("data/raw/oddsportal"),
            Path("data/raw/oddschecker"),
            Path("data/raw/theoddsapi"),
        ):
            if path.exists():
                _remove_tree_best_effort(path)

    async def run_scrapers() -> None:
        await OddsPortalScraper(headless=headless).scrape_all(max_matches)
        scraper = OddscheckerScraper(headless=headless)
        await scraper.scrape_winner_odds()
        await scraper.scrape_top_goalscorer_odds()
        winner_html = Path("input/oddschecker_winner.html")
        topscorer_html = Path("input/oddschecker_top_goalscorer.html")
        if winner_html.is_file():
            await scraper.import_saved_winner_html(winner_html)
        if topscorer_html.is_file():
            await scraper.import_saved_top_goalscorer_html(topscorer_html)

    try:
        asyncio.run(run_scrapers())
    except Exception as exc:
        console.print(f"[yellow]Web scraping failed; fallbacks continue: {exc}[/yellow]")
    try:
        fetch_the_odds_api()
    except Exception as exc:
        console.print(f"[yellow]The Odds API failed; fallbacks continue: {exc}[/yellow]")


def _remove_tree_best_effort(path: Path) -> None:
    def _onerror(func: Any, target_path: str, exc_info: tuple[Any, Any, Any]) -> None:
        error = exc_info[1]
        if isinstance(error, PermissionError):
            try:
                os.chmod(target_path, stat.S_IWRITE)
                func(target_path)
                return
            except Exception:
                pass

        raise error

    try:
        shutil.rmtree(path, onerror=_onerror)
    except PermissionError as exc:
        console.print(
            f"[yellow]Could not fully clear {path}; continuing with existing files: {exc}[/yellow]"
        )


def _run_processing(
    rules_path: Path,
    output_dir: Path,
    prefer_source: str,
    use_manual_fallback: bool,
    *,
    data: PipelineData | None = None,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    _validate_prefer_source(prefer_source)
    rules = load_rules(rules_path)
    data = data or _collect_data(prefer_source, use_manual_fallback)
    timestamp = timestamp or datetime.now().astimezone()

    aggregated_1x2 = aggregate_1x2(data.x1x2)
    aggregated_scores = aggregate_correct_score(data.correct_scores)
    aggregated_ou = aggregate_ou_btts(data.ou_btts)
    aggregated_outrights = aggregate_outrights(data.outrights)
    aggregated_topscorers = aggregate_topscorers(data.topscorers)
    aggregated = (
        aggregated_1x2
        + aggregated_scores
        + aggregated_ou
        + aggregated_outrights
        + aggregated_topscorers
    )
    predictions, candidates, match_failures = optimize_matches(
        data.fixtures,
        aggregated_1x2,
        aggregated_scores,
        rules,
    )
    outright_recommendations = optimize_outrights(
        aggregated_outrights,
        data.outrights,
        rules,
    )
    metadata = resolve_player_metadata(
        data.topscorers,
        api_metadata=data.api_metadata,
        manual_metadata=data.manual_metadata,
    )
    countries = {
        row.player: row.country
        for row in data.topscorers
        if row.country is not None
    }
    topscorer_recommendations = optimize_topscorers(
        aggregated_topscorers,
        metadata,
        outright_recommendations,
        rules,
        countries,
    )
    rankings, consistency_warnings = compute_group_standings(
        data.fixtures,
        predictions,
    )
    correct_outcomes: dict[str, set[str]] = {}
    for row in aggregated_scores:
        correct_outcomes.setdefault(row.entity_id, set()).add(row.outcome)
    quality_warnings = run_quality_gate(
        rules,
        aggregated,
        data.fixtures,
        predictions,
        correct_outcomes,
        metadata,
        topscorer_recommendations,
        timestamp,
    )
    source_failures = data.source_failures + match_failures
    export_all(
        output_dir,
        data.fixtures,
        predictions,
        candidates,
        outright_recommendations,
        rankings,
        consistency_warnings,
        topscorer_recommendations,
        quality_warnings,
        data.validation_errors,
        source_failures,
        len(data.fixtures) - len(predictions),
        timestamp,
    )
    save_json("data/processed/aggregated_markets.json", aggregated)
    save_json("data/processed/match_predictions.json", predictions)
    warning_counts: dict[str, int] = {}
    for warning in quality_warnings:
        warning_counts[warning["check"]] = (
            warning_counts.get(warning["check"], 0) + 1
        )
    for check, count in sorted(warning_counts.items()):
        console.print(
            f"[yellow]QUALITY WARNING {check}: {count} occurrence(s). "
            f"See {output_dir / 'quality_gate_warnings.csv'}.[/yellow]"
        )
    return {
        "predictions": predictions,
        "candidates": candidates,
        "outrights": outright_recommendations,
        "topscorers": topscorer_recommendations,
        "rankings": rankings,
        "quality_warnings": quality_warnings,
    }


def _collect_data(
    prefer_source: str,
    use_manual_fallback: bool,
) -> PipelineData:
    _validate_prefer_source(prefer_source)
    oddsportal = _load_oddsportal()
    api = _load_api()
    oddschecker = _load_oddschecker()
    manual_raw = load_manual_data() if use_manual_fallback or prefer_source == "manual" else ManualData()
    manual = PipelineData(
        fixtures=manual_raw.fixtures,
        x1x2=manual_raw.x1x2,
        correct_scores=manual_raw.correct_scores,
        ou_btts=manual_raw.ou_btts,
        outrights=manual_raw.outrights,
        topscorers=manual_raw.topscorers,
        manual_metadata=manual_raw.player_metadata,
        validation_errors=manual_raw.errors,
    )
    if prefer_source == "manual":
        sources = [manual, oddsportal, api]
    elif prefer_source == "api":
        sources = [api, oddsportal, manual]
    else:
        sources = [oddsportal, api, manual]

    merged = PipelineData()
    merged.fixtures = _merge_fixtures([source.fixtures for source in sources])
    id_maps = [_fixture_id_map(source.fixtures, merged.fixtures) for source in sources]
    merged.x1x2 = _choose_fixture_market(
        [source.x1x2 for source in sources],
        id_maps,
    )
    merged.correct_scores = _choose_fixture_market(
        [source.correct_scores for source in sources],
        id_maps,
    )
    merged.ou_btts = _choose_fixture_market(
        [source.ou_btts for source in sources],
        id_maps,
    )
    merged.outrights = _first_non_empty([source.outrights for source in sources])
    if oddschecker.outrights and prefer_source not in {"api", "manual"}:
        merged.outrights = oddschecker.outrights
    elif not merged.outrights:
        merged.outrights = oddschecker.outrights
    merged.topscorers = oddschecker.topscorers or _first_non_empty(
        [source.topscorers for source in sources]
    )
    if prefer_source == "manual" and manual.topscorers:
        merged.topscorers = manual.topscorers
    merged.api_metadata = _load_models(
        "data/raw/apifootball/parsed_metadata.json",
        PlayerMetadata,
        merged.validation_errors,
    )
    merged.manual_metadata = manual.manual_metadata
    merged.validation_errors.extend(
        error
        for source in sources
        for error in source.validation_errors
    )
    if not oddsportal.fixtures:
        merged.source_failures.append("OddsPortal fixtures unavailable.")
    if not oddschecker.outrights:
        merged.source_failures.append("Oddschecker winner odds unavailable.")
    if not oddschecker.topscorers:
        merged.source_failures.append("Oddschecker topscorer odds unavailable.")
    return merged


def _load_oddsportal() -> PipelineData:
    data = PipelineData()
    data.fixtures = _load_models(
        "data/raw/oddsportal/fixtures.json",
        Fixture,
        data.validation_errors,
    )
    root = Path("data/raw/oddsportal")
    for path in root.glob("*.json") if root.exists() else []:
        if path.name in {
            "fixtures.json",
            "fixtures_status.json",
            "outrights.json",
        }:
            continue
        payload = load_json(path, {})
        if payload.get("failed"):
            data.source_failures.append(
                f"OddsPortal {payload.get('fixture_id', path.stem)}: {payload['failed']}"
            )
            continue
        data.x1x2.extend(_parse_models(payload.get("x1x2", []), Raw1X2Odd, path, data))
        data.correct_scores.extend(
            _parse_models(
                payload.get("correct_scores", []),
                RawCorrectScoreOdd,
                path,
                data,
            )
        )
        data.ou_btts.extend(
            _parse_models(payload.get("ou_btts", []), RawOUBTTSOdd, path, data)
        )
    status = load_json(root / "fixtures_status.json", {}) or {}
    if status.get("status") == "FAILED":
        data.source_failures.extend(
            f"OddsPortal fixtures: {failure}"
            for failure in status.get("failures", [])
        )
    data.outrights = _load_models(
        root / "outrights.json",
        RawOutrightOdd,
        data.validation_errors,
    )
    return data


def _load_oddschecker() -> PipelineData:
    data = PipelineData()
    data.outrights = _load_models(
        "data/raw/oddschecker/winner.json",
        RawOutrightOdd,
        data.validation_errors,
    )
    data.topscorers = _load_models(
        "data/raw/oddschecker/top_goalscorer.json",
        RawTopGoalscorerOdd,
        data.validation_errors,
    )
    for filename, label in (
        ("winner_status.json", "winner"),
        ("top_goalscorer_status.json", "top goalscorer"),
    ):
        status = load_json(Path("data/raw/oddschecker") / filename, {}) or {}
        if status.get("status") == "FAILED":
            data.source_failures.extend(
                f"Oddschecker {label}: {failure}"
                for failure in status.get("failures", [])
            )
    return data


def _load_api() -> PipelineData:
    data = PipelineData()
    payload = load_json("data/raw/theoddsapi/parsed.json", {}) or {}
    for key, model in (
        ("fixtures", Fixture),
        ("x1x2", Raw1X2Odd),
        ("correct_scores", RawCorrectScoreOdd),
        ("ou_btts", RawOUBTTSOdd),
        ("outrights", RawOutrightOdd),
        ("topscorers", RawTopGoalscorerOdd),
    ):
        setattr(
            data,
            key,
            _parse_models(payload.get(key, []), model, Path("theoddsapi"), data),
        )
    return data


def _load_models(
    path: str | Path,
    model: type[T],
    errors: list[dict[str, str]],
) -> list[T]:
    source = Path(path)
    payload = load_json(source, []) or []
    holder = PipelineData(validation_errors=errors)
    return _parse_models(payload, model, source, holder)


def _parse_models(
    payload: list[dict[str, Any]],
    model: type[T],
    source: Path,
    data: PipelineData,
) -> list[T]:
    output: list[T] = []
    for index, row in enumerate(payload):
        try:
            output.append(model.model_validate(row))
        except (ValidationError, ValueError) as exc:
            data.validation_errors.append(
                {"file": str(source), "line": str(index + 1), "error": str(exc)}
            )
    return output


def _merge_fixtures(groups: list[list[Fixture]]) -> list[Fixture]:
    output: dict[tuple[str, str], Fixture] = {}
    ids: set[str] = set()
    for fixtures in groups:
        for fixture in fixtures:
            key = _fixture_key(fixture)
            if key in output or fixture.fixture_id in ids:
                continue
            output[key] = fixture
            ids.add(fixture.fixture_id)
    return sorted(output.values(), key=lambda row: row.kickoff_datetime)


def _fixture_key(fixture: Fixture) -> tuple[str, str]:
    teams = "|".join(
        value.casefold().strip()
        for value in (fixture.home_team, fixture.away_team)
    )
    return fixture.kickoff_datetime.date().isoformat(), teams


def _fixture_id_map(
    source: list[Fixture],
    merged: list[Fixture],
) -> dict[str, str]:
    by_key = {_fixture_key(fixture): fixture.fixture_id for fixture in merged}
    return {
        fixture.fixture_id: by_key.get(_fixture_key(fixture), fixture.fixture_id)
        for fixture in source
    }


def _choose_fixture_market(
    groups: list[list[T]],
    id_maps: list[dict[str, str]],
) -> list[T]:
    selected: dict[str, list[T]] = {}
    for rows, id_map in zip(groups, id_maps, strict=True):
        by_fixture: dict[str, list[T]] = {}
        for row in rows:
            original_id = str(getattr(row, "fixture_id"))
            target_id = id_map.get(original_id, original_id)
            updated = (
                row.model_copy(update={"fixture_id": target_id})
                if target_id != original_id
                else row
            )
            by_fixture.setdefault(target_id, []).append(updated)
        for fixture_id, fixture_rows in by_fixture.items():
            selected.setdefault(fixture_id, fixture_rows)
    return [row for fixture_rows in selected.values() for row in fixture_rows]


def _first_non_empty(groups: list[list[T]]) -> list[T]:
    return next((group for group in groups if group), [])


def _manual_to_dict(manual: ManualData) -> dict[str, Any]:
    return {
        "fixtures": manual.fixtures,
        "x1x2": manual.x1x2,
        "correct_scores": manual.correct_scores,
        "ou_btts": manual.ou_btts,
        "outrights": manual.outrights,
        "topscorers": manual.topscorers,
        "player_metadata": manual.player_metadata,
        "errors": manual.errors,
    }


def _top_player_country_pairs(
    rows: list[RawTopGoalscorerOdd],
    limit: int = 100,
) -> list[tuple[str, str | None]]:
    countries: dict[str, str | None] = {}
    for row in rows:
        if row.country:
            countries.setdefault(row.player.casefold(), row.country)
    ranked = sorted(
        aggregate_topscorers(rows),
        key=lambda row: (-row.probability, row.outcome.casefold()),
    )
    return [
        (row.outcome, countries.get(row.outcome.casefold()))
        for row in ranked[:limit]
    ]


def _validate_prefer_source(value: str) -> None:
    if value not in {"oddsportal", "api", "mixed", "manual"}:
        raise typer.BadParameter(
            "--prefer-source must be oddsportal, api, mixed, or manual"
        )


def _parse_bool(value: str, option_name: str) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise typer.BadParameter(f"{option_name} must be true or false")


if __name__ == "__main__":
    app()
