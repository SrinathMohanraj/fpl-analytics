"""Value-pick analytics: who's worth their price, who's in form, who to target."""
from __future__ import annotations

import pandas as pd

MIN_MINUTES = 90  # filter out players who've barely featured


def add_value_score(players: pd.DataFrame) -> pd.DataFrame:
    """Add points-per-million and a blended value score to the players table.

    value_score blends season-long output (points per million) with recent
    form, so a cheap player on a hot streak ranks above a similarly-priced
    player coasting on early-season points.
    """
    df = players.copy()
    df["points_per_million"] = (df["total_points"] / df["price_m"]).round(2)
    df["form_per_million"] = (df["form"] / df["price_m"]).round(2)
    # 60/40 blend: season value still matters most, but form nudges rankings
    df["value_score"] = (
        0.6 * df["points_per_million"].rank(pct=True)
        + 0.4 * df["form_per_million"].rank(pct=True)
    ).round(3)
    return df


def top_value_picks(players: pd.DataFrame, position: str | None = None,
                     max_price: float | None = None, top_n: int = 10) -> pd.DataFrame:
    """Best value players right now, optionally filtered by position / budget."""
    df = add_value_score(players)
    df = df[df["minutes"] >= MIN_MINUTES]
    df = df[df["status"] == "a"]  # available (not injured/suspended)

    if position:
        df = df[df["position"] == position.upper()]
    if max_price:
        df = df[df["price_m"] <= max_price]

    cols = ["web_name", "team_name", "position", "price_m", "total_points",
            "form", "points_per_million", "value_score"]
    return df.sort_values("value_score", ascending=False)[cols].head(top_n).reset_index(drop=True)


def differentials(players: pd.DataFrame, max_ownership: float = 10.0, top_n: int = 10) -> pd.DataFrame:
    """Low-ownership players still putting up strong form — climb-the-rank picks."""
    df = players[(players["minutes"] >= MIN_MINUTES) & (players["status"] == "a")]
    df = df[df["selected_by_percent"] <= max_ownership]
    cols = ["web_name", "team_name", "position", "price_m", "total_points",
            "form", "selected_by_percent"]
    return df.sort_values("form", ascending=False)[cols].head(top_n).reset_index(drop=True)


def injury_watch(players: pd.DataFrame) -> pd.DataFrame:
    """Players with fitness doubts — status != available."""
    df = players[players["status"] != "a"]
    cols = ["web_name", "team_name", "position", "price_m", "status",
            "chance_of_playing_next_round"]
    return df[cols].reset_index(drop=True)
