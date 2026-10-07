"""Export tidy star-schema tables for Power BI (or Tableau / Excel).

Star schema = a few small lookup tables ("dimensions") that describe things
(players, teams, gameweeks) and a few big tables ("facts") that record what
happened (points per player per gameweek, who was in my squad, fixtures).
Power BI relates them by ID columns, which keeps DAX simple and fast.

    dim_team        dim_player        dim_gameweek
        \\              |               /
         +-- fact_player_gw -----------+
         +-- fact_my_squad
         +-- fact_my_gw
         +-- fact_team_fixture

Written to data/powerbi/*.csv by pipeline.py on every run.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# stats we keep from the /event/<gw>/live/ endpoint (missing ones become 0)
LIVE_STAT_COLUMNS = [
    "minutes", "total_points", "goals_scored", "assists", "clean_sheets",
    "goals_conceded", "saves", "bonus", "bps", "yellow_cards", "red_cards",
    "expected_goals", "expected_assists", "expected_goal_involvements",
    "defensive_contribution",
]


def build_dim_team(bootstrap: dict) -> pd.DataFrame:
    df = pd.DataFrame(bootstrap["teams"])
    return df.rename(columns={"id": "team_id", "name": "team_name"})[
        ["team_id", "team_name", "short_name", "strength"]
    ]


def build_dim_player(bootstrap: dict) -> pd.DataFrame:
    df = pd.DataFrame(bootstrap["elements"])
    df["position"] = df["element_type"].map(POSITION_MAP)
    df["price_m"] = df["now_cost"] / 10.0
    df["full_name"] = df["first_name"].str.cat(df["second_name"], sep=" ")
    df["selected_by_percent"] = pd.to_numeric(df["selected_by_percent"], errors="coerce")
    df["form"] = pd.to_numeric(df["form"], errors="coerce")
    df = df.rename(columns={"id": "player_id", "team": "team_id"})
    return df[[
        "player_id", "web_name", "full_name", "team_id", "position", "price_m",
        "selected_by_percent", "form", "total_points", "status",
    ]]


def build_dim_gameweek(bootstrap: dict) -> pd.DataFrame:
    df = pd.DataFrame(bootstrap["events"]).rename(columns={"id": "gameweek"})
    df["deadline_time"] = pd.to_datetime(df.get("deadline_time"), errors="coerce", utc=True)
    df["deadline_date"] = df["deadline_time"].dt.date
    keep = ["gameweek", "name", "deadline_date", "finished", "is_current"]
    return df[[c for c in keep if c in df.columns]]


def build_fact_player_gw(event_live: dict) -> pd.DataFrame:
    rows = []
    for gw, payload in event_live.items():
        for el in payload["elements"]:
            stats = el["stats"]
            row = {"player_id": el["id"], "gameweek": int(gw)}
            for col in LIVE_STAT_COLUMNS:
                row[col] = pd.to_numeric(stats.get(col, 0), errors="coerce")
            rows.append(row)
    df = pd.DataFrame(rows)
    return df.fillna(0).sort_values(["gameweek", "player_id"]).reset_index(drop=True)


def build_fact_my_squad(picks_by_gw: dict, fact_player_gw: pd.DataFrame) -> pd.DataFrame:
    """One row per owned player per gameweek, with points that actually counted.

    Handles automatic substitutions: a bench player who came on counts as a
    starter, and the starter they replaced counts as benched.
    """
    pts = fact_player_gw.set_index(["gameweek", "player_id"])["total_points"]
    rows = []
    for gw, payload in picks_by_gw.items():
        gw = int(gw)
        subs_in = {s["element_in"] for s in payload.get("automatic_subs", [])}
        subs_out = {s["element_out"] for s in payload.get("automatic_subs", [])}
        for p in payload["picks"]:
            pid, slot, mult = p["element"], p["position"], p["multiplier"]
            raw_points = float(pts.get((gw, pid), 0))
            # multiplier > 0 means 'counts' (covers Bench Boost, where bench players have 1)
            started = (mult > 0 and pid not in subs_out) or pid in subs_in
            eff_mult = (mult if mult > 0 else 1) if started else 0
            rows.append({
                "gameweek": gw,
                "player_id": pid,
                "squad_slot": slot,
                "is_captain": bool(p["is_captain"]),
                "is_vice_captain": bool(p["is_vice_captain"]),
                "started": started,
                "multiplier": eff_mult,
                "player_points": raw_points,
                "points_counted": raw_points * eff_mult,
                "points_on_bench": 0.0 if started else raw_points,
            })
    return pd.DataFrame(rows).sort_values(["gameweek", "squad_slot"]).reset_index(drop=True)


def build_fact_my_gw(history_df: pd.DataFrame, fact_my_squad: pd.DataFrame) -> pd.DataFrame:
    """Official gameweek history plus our own recomputed points as a sanity check."""
    calc = (fact_my_squad.groupby("gameweek")["points_counted"].sum()
            .rename("calc_points").reset_index())
    df = history_df.merge(calc, on="gameweek", how="left")
    df["points_diff_vs_official"] = df["calc_points"] - df["points"]
    return df


def build_fact_team_fixture(fixtures: list) -> pd.DataFrame:
    """Long format: one row per team per fixture (home and away both listed)."""
    rows = []
    for f in fixtures:
        if f.get("event") is None:
            continue  # unscheduled / postponed
        base = {"gameweek": f["event"], "kickoff_time": f.get("kickoff_time"),
                "finished": bool(f.get("finished"))}
        rows.append({**base, "team_id": f["team_h"], "opponent_id": f["team_a"],
                     "is_home": True, "difficulty": f.get("team_h_difficulty"),
                     "goals_for": f.get("team_h_score"), "goals_against": f.get("team_a_score")})
        rows.append({**base, "team_id": f["team_a"], "opponent_id": f["team_h"],
                     "is_home": False, "difficulty": f.get("team_a_difficulty"),
                     "goals_for": f.get("team_a_score"), "goals_against": f.get("team_h_score")})
    cols = ["gameweek", "kickoff_time", "finished", "team_id", "opponent_id",
            "is_home", "difficulty", "goals_for", "goals_against"]
    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values(["gameweek", "team_id"]).reset_index(drop=True)


def export_all(raw: dict, history_df: pd.DataFrame, out_dir: Path) -> dict[str, pd.DataFrame]:
    """Build every table and write them as UTF-8 CSVs into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    fact_player_gw = build_fact_player_gw(raw["event_live"])
    fact_my_squad = build_fact_my_squad(raw["picks_by_gw"], fact_player_gw)

    tables = {
        "dim_team": build_dim_team(raw["bootstrap"]),
        "dim_player": build_dim_player(raw["bootstrap"]),
        "dim_gameweek": build_dim_gameweek(raw["bootstrap"]),
        "fact_player_gw": fact_player_gw,
        "fact_my_squad": fact_my_squad,
        "fact_my_gw": build_fact_my_gw(history_df, fact_my_squad),
        "fact_team_fixture": build_fact_team_fixture(raw["fixtures"]),
    }
    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False, encoding="utf-8")
    return tables
