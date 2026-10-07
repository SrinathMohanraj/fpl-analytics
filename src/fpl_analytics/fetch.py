"""Data retrieval from the official Fantasy Premier League API.

The FPL API is public and needs no authentication:
https://fantasy.premierleague.com/api/

This module only performs HTTP GETs and returns raw JSON (dicts/lists).
Any cleaning or shaping happens downstream in `clean.py`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://fantasy.premierleague.com/api"
USER_AGENT = "fpl-analytics/0.1 (+https://github.com/)"
TIMEOUT = 15
RETRIES = 3
BACKOFF_SECONDS = 2


def _get(path: str) -> Any:
    """GET a path under BASE_URL with simple retry/backoff, return parsed JSON."""
    url = f"{BASE_URL}/{path.lstrip('/')}"
    last_exc: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:  # noqa: PERF203 - retry loop is intentional
            last_exc = exc
            if attempt < RETRIES:
                time.sleep(BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"Failed to fetch {url} after {RETRIES} attempts") from last_exc


def get_bootstrap_static() -> dict:
    """Core dataset: all players, teams, gameweeks (events), game settings."""
    return _get("bootstrap-static/")


def get_fixtures(event: int | None = None) -> list:
    """All fixtures, or fixtures for a single gameweek if `event` is given."""
    path = "fixtures/" if event is None else f"fixtures/?event={event}"
    return _get(path)


def get_player_summary(player_id: int) -> dict:
    """Per-gameweek history and upcoming fixtures for a single player (element)."""
    return _get(f"element-summary/{player_id}/")


def get_entry(entry_id: int) -> dict:
    """A manager's team overview (name, overall rank, value, leagues joined)."""
    return _get(f"entry/{entry_id}/")


def get_entry_history(entry_id: int) -> dict:
    """A manager's gameweek-by-gameweek history for the current season + past seasons."""
    return _get(f"entry/{entry_id}/history/")


def get_entry_picks(entry_id: int, event: int) -> dict:
    """A manager's squad selection (picks, captain, chips used) for one gameweek."""
    return _get(f"entry/{entry_id}/event/{event}/picks/")


def get_entry_transfers(entry_id: int) -> list:
    """Full transfer history for a manager this season."""
    return _get(f"entry/{entry_id}/transfers/")


def get_event_live(event: int) -> dict:
    """Every player's actual stats and points for one gameweek (1 call per GW)."""
    return _get(f"event/{event}/live/")


def fetch_history_by_gameweek(entry_id: int, up_to_event: int) -> tuple[dict, dict]:
    """Per-gameweek live stats and squad picks for gameweeks 1..up_to_event.

    Feeds the Power BI export (player-by-gameweek facts and 'who did I own').
    Returns ({gw: live_json}, {gw: picks_json}) keyed by gameweek number.
    """
    live: dict[int, dict] = {}
    picks: dict[int, dict] = {}
    for gw in range(1, up_to_event + 1):
        live[gw] = get_event_live(gw)
        picks[gw] = get_entry_picks(entry_id, gw)
    return live, picks


def fetch_all_for_pipeline(entry_id: int, raw_dir: Path) -> dict[str, Any]:
    """Pull everything the pipeline needs and cache raw JSON to disk.

    Returns a dict of the in-memory payloads as well, so pipeline.py can
    proceed without re-reading from disk.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)

    bootstrap = get_bootstrap_static()
    current_event = next(
        (e["id"] for e in bootstrap["events"] if e.get("is_current")),
        max(e["id"] for e in bootstrap["events"] if e.get("finished")),
    )

    fixtures = get_fixtures()
    entry = get_entry(entry_id)
    entry_history = get_entry_history(entry_id)
    entry_picks = get_entry_picks(entry_id, current_event)
    entry_transfers = get_entry_transfers(entry_id)
    event_live, picks_by_gw = fetch_history_by_gameweek(entry_id, current_event)

    payload = {
        "event_live": event_live,
        "picks_by_gw": picks_by_gw,
        "bootstrap": bootstrap,
        "fixtures": fixtures,
        "entry": entry,
        "entry_history": entry_history,
        "entry_picks": entry_picks,
        "entry_transfers": entry_transfers,
        "current_event": current_event,
    }

    for name, data in payload.items():
        if name == "current_event":
            continue
        (raw_dir / f"{name}.json").write_text(json.dumps(data, indent=2))

    return payload


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch raw FPL data for one manager entry.")
    parser.add_argument("entry_id", type=int, help="Your FPL team/entry ID")
    parser.add_argument("--out", type=Path, default=Path("data/raw"), help="Output directory")
    args = parser.parse_args()

    result = fetch_all_for_pipeline(args.entry_id, args.out)
    print(f"Fetched data for entry {args.entry_id}, current gameweek {result['current_event']}")
