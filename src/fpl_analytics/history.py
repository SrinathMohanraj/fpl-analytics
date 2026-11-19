"""Daily snapshots of team value and player prices, kept as a growing history.

FPL prices change overnight (around 01:30 UK time), but the API only ever
shows *today's* price. So every pipeline run appends one dated snapshot to two
history tables instead of overwriting them:

    fact_value_daily  one row per day: my squad's market value, bank, total
    fact_price_daily  one row per player per day: price, ownership, transfers

Re-running on the same day replaces that day's rows (no duplicates). The
tables live next to the other Power BI CSVs in data/powerbi/.

Note on "value": squad_value here is the sum of the CURRENT prices of the 15
players picked for the current gameweek (what the FPL app calls team value).
Your selling value can be lower, because FPL only gives you half of any
price rise. Transfers you make for the next gameweek only show up in the
public API after that gameweek's deadline.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

VALUE_COLUMNS = [
    "snapshot_date", "gameweek", "squad_value", "bank", "team_value",
    "value_change", "players_rising", "players_falling",
]
PRICE_COLUMNS = [
    "snapshot_date", "gameweek", "player_id", "price_m", "price_change",
    "selected_by_percent", "transfers_in_event", "transfers_out_event", "in_my_squad",
]


def build_price_snapshot(bootstrap: dict, owned_ids: set[int], gameweek: int,
                         snapshot_date: date) -> pd.DataFrame:
    """One row per player with today's price (price_change filled in later)."""
    df = pd.DataFrame(bootstrap["elements"])
    out = pd.DataFrame({
        "snapshot_date": snapshot_date.isoformat(),
        "gameweek": gameweek,
        "player_id": df["id"],
        "price_m": df["now_cost"] / 10.0,
        "price_change": 0.0,
        "selected_by_percent": pd.to_numeric(df["selected_by_percent"], errors="coerce"),
        "transfers_in_event": df.get("transfers_in_event", 0),
        "transfers_out_event": df.get("transfers_out_event", 0),
        "in_my_squad": df["id"].isin(owned_ids),
    })
    return out[PRICE_COLUMNS]


def build_value_snapshot(price_snapshot: pd.DataFrame, entry_picks: dict, gameweek: int,
                         snapshot_date: date) -> pd.DataFrame:
    """One row: today's market value of my 15 players, plus money in the bank."""
    squad_value = round(float(price_snapshot.loc[price_snapshot["in_my_squad"], "price_m"].sum()), 1)
    bank = entry_picks.get("entry_history", {}).get("bank", 0) / 10.0
    return pd.DataFrame([{
        "snapshot_date": snapshot_date.isoformat(),
        "gameweek": gameweek,
        "squad_value": squad_value,
        "bank": bank,
        "team_value": round(squad_value + bank, 1),
        "value_change": 0.0,
        "players_rising": 0,
        "players_falling": 0,
    }])[VALUE_COLUMNS]


def _read_existing(path: Path, columns: list[str]) -> pd.DataFrame:
    if path.exists() and path.stat().st_size > 0:
        df = pd.read_csv(path)
        if not df.empty:
            return df
    return pd.DataFrame(columns=columns)


def upsert_prices(path: Path, snapshot: pd.DataFrame) -> pd.DataFrame:
    """Add today's prices to the history file and recompute day-on-day changes."""
    today = snapshot["snapshot_date"].iloc[0]
    old = _read_existing(path, PRICE_COLUMNS)
    old = old[old["snapshot_date"] != today]
    df = pd.concat([old, snapshot], ignore_index=True) if not old.empty else snapshot.copy()
    df = df.sort_values(["player_id", "snapshot_date"]).reset_index(drop=True)
    prev = df.groupby("player_id")["price_m"].shift(1)
    df["price_change"] = (df["price_m"] - prev).fillna(0.0).round(1)
    df = df.sort_values(["snapshot_date", "player_id"]).reset_index(drop=True)
    df = df[PRICE_COLUMNS]
    df.to_csv(path, index=False, encoding="utf-8")
    return df


def upsert_value(path: Path, snapshot: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Add today's team value to the history file and recompute daily change."""
    today = snapshot["snapshot_date"].iloc[0]
    old = _read_existing(path, VALUE_COLUMNS)
    old = old[old["snapshot_date"] != today]
    df = pd.concat([old, snapshot], ignore_index=True) if not old.empty else snapshot.copy()
    df = df.sort_values("snapshot_date").reset_index(drop=True)
    df["value_change"] = df["team_value"].diff().fillna(0.0).round(1)

    # how many of my players moved in price today
    mine_today = prices[(prices["snapshot_date"] == today) & prices["in_my_squad"].astype(bool)]
    is_today = df["snapshot_date"] == today
    df.loc[is_today, "players_rising"] = int((mine_today["price_change"] > 0).sum())
    df.loc[is_today, "players_falling"] = int((mine_today["price_change"] < 0).sum())
    df["players_rising"] = df["players_rising"].fillna(0).astype(int)
    df["players_falling"] = df["players_falling"].fillna(0).astype(int)

    df = df[VALUE_COLUMNS]
    df.to_csv(path, index=False, encoding="utf-8")
    return df


def record_daily_snapshot(raw: dict, out_dir: Path,
                          snapshot_date: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Append today's value and price snapshot; return (value_history, price_history)."""
    snapshot_date = snapshot_date or datetime.now(timezone.utc).date()
    out_dir.mkdir(parents=True, exist_ok=True)
    gameweek = int(raw["current_event"])
    owned = {p["element"] for p in raw["entry_picks"]["picks"]}

    price_snap = build_price_snapshot(raw["bootstrap"], owned, gameweek, snapshot_date)
    value_snap = build_value_snapshot(price_snap, raw["entry_picks"], gameweek, snapshot_date)

    prices = upsert_prices(out_dir / "fact_price_daily.csv", price_snap)
    values = upsert_value(out_dir / "fact_value_daily.csv", value_snap, prices)
    return values, prices


def squad_price_moves(prices: pd.DataFrame, bootstrap: dict) -> list[dict]:
    """My players whose price changed on the latest snapshot day (for the dashboard)."""
    if prices.empty:
        return []
    latest = prices["snapshot_date"].max()
    moved = prices[(prices["snapshot_date"] == latest)
                   & prices["in_my_squad"].astype(bool)
                   & (prices["price_change"] != 0)]
    names = {e["id"]: e["web_name"] for e in bootstrap["elements"]}
    return [
        {"web_name": names.get(int(r.player_id), str(r.player_id)),
         "price_m": float(r.price_m), "price_change": float(r.price_change)}
        for r in moved.itertuples()
    ]
