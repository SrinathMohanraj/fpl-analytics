"""Squad tracker: how YOUR team (one FPL entry ID) is performing over the season."""
from __future__ import annotations

import pandas as pd


def season_summary(entry: dict, history_df: pd.DataFrame) -> dict:
    """Headline numbers for the dashboard's top strip."""
    latest = history_df.iloc[-1]
    best_gw = history_df.loc[history_df["points"].idxmax()]
    worst_gw = history_df.loc[history_df["points"].idxmin()]

    rank_start = history_df.iloc[0]["overall_rank"]
    rank_now = latest["overall_rank"]
    rank_delta = int(rank_start - rank_now)  # positive = climbed

    return {
        "manager_name": f"{entry.get('player_first_name', '')} {entry.get('player_last_name', '')}".strip(),
        "team_name": entry.get("name"),
        "current_gameweek": int(latest["gameweek"]),
        "total_points": int(latest["total_points"]),
        "overall_rank": int(rank_now),
        "rank_climbed": rank_delta,
        "team_value": float(latest["team_value"]),
        "bank": float(latest["bank"]),
        "total_bench_points_wasted": int(history_df["bench_points"].sum()),
        "total_transfer_cost": int(history_df["transfer_cost"].sum()),
        "best_gameweek": {"gw": int(best_gw["gameweek"]), "points": int(best_gw["points"])},
        "worst_gameweek": {"gw": int(worst_gw["gameweek"]), "points": int(worst_gw["points"])},
    }


def rank_trend(history_df: pd.DataFrame) -> pd.DataFrame:
    """Gameweek-by-gameweek points and overall rank — the two headline time series."""
    return history_df[["gameweek", "points", "total_points", "overall_rank", "bench_points"]].copy()


def bench_waste_by_gw(history_df: pd.DataFrame) -> pd.DataFrame:
    """Points left on the bench each gameweek — a classic self-inflicted FPL wound."""
    df = history_df[["gameweek", "bench_points"]].copy()
    df["cumulative_bench_points"] = df["bench_points"].cumsum()
    return df


def current_squad_breakdown(picks_df: pd.DataFrame) -> dict:
    """Split the latest picks into starters / bench / captaincy for the dashboard."""
    starters = picks_df[picks_df["starting"]]
    bench = picks_df[~picks_df["starting"]]
    captain_row = picks_df[picks_df["role"] == "Captain"]
    return {
        "starting_xi": starters.drop(columns=["starting"]).to_dict(orient="records"),
        "bench": bench.drop(columns=["starting"]).to_dict(orient="records"),
        "captain": captain_row["web_name"].iloc[0] if not captain_row.empty else None,
    }
