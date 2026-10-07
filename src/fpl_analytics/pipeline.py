"""Orchestrates the full weekly workflow: fetch -> clean -> analyze -> export.

Run with:
    python -m fpl_analytics.pipeline <your_entry_id>

Produces data/processed/dashboard.json, which dashboard/index.html reads
directly (no backend/server needed — it's a static file).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import clean, fetch, metrics, powerbi, squad

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "raw"
DEFAULT_PROCESSED_DIR = REPO_ROOT / "data" / "processed"
DASHBOARD_DATA_DIR = REPO_ROOT / "dashboard" / "data"
POWERBI_DIR = REPO_ROOT / "data" / "powerbi"


def _current_event_from_bootstrap(bootstrap: dict) -> int:
    return next(
        (e["id"] for e in bootstrap["events"] if e.get("is_current")),
        max(e["id"] for e in bootstrap["events"] if e.get("finished")),
    )


def run(entry_id: int, raw_dir: Path = DEFAULT_RAW_DIR,
         processed_dir: Path = DEFAULT_PROCESSED_DIR) -> Path:
    """Full pipeline against the LIVE FPL API (needs internet access)."""
    raw = fetch.fetch_all_for_pipeline(entry_id, raw_dir)
    return _process(entry_id, raw, processed_dir, is_demo=False)


def run_from_raw(entry_id: int, raw_dir: Path = DEFAULT_RAW_DIR,
                   processed_dir: Path = DEFAULT_PROCESSED_DIR, is_demo: bool = True) -> Path:
    """Run the clean/analyze/export stages against already-fetched raw JSON.

    Used for local testing and for the bundled demo dataset, so the pipeline
    logic can be exercised without hitting the live API. `is_demo` is stamped
    into the output so the dashboard can show an honest "sample data" banner.
    """
    raw = {
        name: json.loads((raw_dir / f"{name}.json").read_text())
        for name in ("bootstrap", "fixtures", "entry", "entry_history",
                      "entry_picks", "entry_transfers", "event_live", "picks_by_gw")
        if (raw_dir / f"{name}.json").exists()
    }
    raw["current_event"] = _current_event_from_bootstrap(raw["bootstrap"])
    return _process(entry_id, raw, processed_dir, is_demo=is_demo)


def _process(entry_id: int, raw: dict, processed_dir: Path, is_demo: bool) -> Path:
    # 2. Clean -------------------------------------------------------------
    players = clean.players_df(raw["bootstrap"])
    history = clean.entry_history_df(raw["entry_history"])
    picks = clean.entry_picks_df(raw["entry_picks"], players)

    # 3. Analyze -------------------------------------------------------------
    players_scored = metrics.add_value_score(players)
    value_picks_overall = metrics.top_value_picks(players, top_n=15)
    value_picks_by_position = {
        pos: metrics.top_value_picks(players, position=pos, top_n=8).to_dict(orient="records")
        for pos in ["GKP", "DEF", "MID", "FWD"]
    }
    diffs = metrics.differentials(players, top_n=10)
    injuries = metrics.injury_watch(players)

    summary = squad.season_summary(raw["entry"], history)
    trend = squad.rank_trend(history)
    bench_waste = squad.bench_waste_by_gw(history)
    squad_now = squad.current_squad_breakdown(picks)

    # 4. Visualize / Export --------------------------------------------------
    processed_dir.mkdir(parents=True, exist_ok=True)
    dashboard_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "is_demo": is_demo,
        "entry_id": entry_id,
        "current_gameweek": raw["current_event"],
        "summary": summary,
        "rank_trend": trend.to_dict(orient="records"),
        "bench_waste": bench_waste.to_dict(orient="records"),
        "current_squad": squad_now,
        "value_picks_overall": value_picks_overall.to_dict(orient="records"),
        "value_picks_by_position": value_picks_by_position,
        "differentials": diffs.to_dict(orient="records"),
        "injury_watch": injuries.to_dict(orient="records"),
    }

    out_path = processed_dir / "dashboard.json"
    payload_json = json.dumps(dashboard_payload, indent=2, default=str)
    out_path.write_text(payload_json)

    # mirror into dashboard/data/ so the static dashboard (served from the
    # dashboard/ folder on GitHub Pages, or opened locally) always has the
    # latest data without a separate copy step
    DASHBOARD_DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DASHBOARD_DATA_DIR / "dashboard.json").write_text(payload_json)

    # also drop tidy CSVs for anyone who wants to open this in Excel,
    # matching the "Python und Excel" half of the workflow
    players_scored.to_csv(processed_dir / "players_scored.csv", index=False)
    history.to_csv(processed_dir / "gameweek_history.csv", index=False)

    # Power BI / Tableau / Excel tables (star schema), only when per-gameweek
    # data was fetched
    if "event_live" in raw and "picks_by_gw" in raw:
        tables = powerbi.export_all(raw, history, POWERBI_DIR)
        print(f"Power BI tables -> {POWERBI_DIR} ({', '.join(tables)})")

    print(f"Pipeline complete -> {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full FPL analytics pipeline.")
    parser.add_argument("entry_id", type=int, help="Your FPL team/entry ID")
    args = parser.parse_args()
    run(args.entry_id)


if __name__ == "__main__":
    main()
