"""Clean / normalize raw FPL API JSON into tidy pandas DataFrames."""
from __future__ import annotations

import pandas as pd

POSITION_MAP = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}


def players_df(bootstrap: dict) -> pd.DataFrame:
    """One row per player (FPL calls them 'elements') with human-readable fields."""
    df = pd.DataFrame(bootstrap["elements"])
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}

    df["team_name"] = df["team"].map(teams)
    df["position"] = df["element_type"].map(POSITION_MAP)
    df["price_m"] = df["now_cost"] / 10.0
    df["full_name"] = df["first_name"].str.cat(df["second_name"], sep=" ")
    df["form"] = pd.to_numeric(df["form"], errors="coerce")
    df["points_per_game"] = pd.to_numeric(df["points_per_game"], errors="coerce")
    df["selected_by_percent"] = pd.to_numeric(df["selected_by_percent"], errors="coerce")
    df["ict_index"] = pd.to_numeric(df["ict_index"], errors="coerce")

    keep = [
        "id", "full_name", "web_name", "team_name", "position", "price_m",
        "total_points", "form", "points_per_game", "minutes", "goals_scored",
        "assists", "clean_sheets", "bonus", "selected_by_percent", "ict_index",
        "status", "chance_of_playing_next_round",
    ]
    return df[keep].copy()


def teams_df(bootstrap: dict) -> pd.DataFrame:
    df = pd.DataFrame(bootstrap["teams"])
    return df[["id", "name", "short_name", "strength",
               "strength_overall_home", "strength_overall_away"]].copy()


def fixtures_df(fixtures: list, bootstrap: dict) -> pd.DataFrame:
    df = pd.DataFrame(fixtures)
    teams = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    df["home_team"] = df["team_h"].map(teams)
    df["away_team"] = df["team_a"].map(teams)
    keep = [
        "event", "kickoff_time", "home_team", "away_team",
        "team_h_difficulty", "team_a_difficulty", "finished",
        "team_h_score", "team_a_score",
    ]
    return df[keep].copy()


def entry_history_df(entry_history: dict) -> pd.DataFrame:
    """One row per gameweek: points, overall rank, bank, team value, transfers."""
    df = pd.DataFrame(entry_history["current"])
    rename = {
        "event": "gameweek",
        "points": "points",
        "total_points": "total_points",
        "rank": "gw_rank",
        "overall_rank": "overall_rank",
        "bank": "bank",
        "value": "team_value",
        "event_transfers": "transfers_made",
        "event_transfers_cost": "transfer_cost",
        "points_on_bench": "bench_points",
    }
    df = df.rename(columns=rename)
    df["bank"] = df["bank"] / 10.0
    df["team_value"] = df["team_value"] / 10.0
    return df[list(rename.values())].copy()


def entry_picks_df(entry_picks: dict, players: pd.DataFrame) -> pd.DataFrame:
    """Current gameweek squad: who's playing, captain/vice, bench order."""
    df = pd.DataFrame(entry_picks["picks"]).rename(columns={"position": "squad_slot"})
    df = df.merge(players[["id", "full_name", "web_name", "position", "team_name", "price_m"]],
                   left_on="element", right_on="id", how="left")
    df["role"] = df.apply(
        lambda r: "Captain" if r["is_captain"] else ("Vice-Captain" if r["is_vice_captain"] else ""),
        axis=1,
    )
    df["starting"] = df["multiplier"] > 0
    keep = ["squad_slot", "position", "web_name", "team_name", "price_m",
            "multiplier", "role", "starting"]
    keep = [c for c in keep if c in df.columns]
    return df[keep].sort_values("squad_slot").reset_index(drop=True)
