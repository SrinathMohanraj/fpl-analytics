"""Checks for the daily team value / price history — run with: pytest"""
from datetime import date

import pandas as pd

from fpl_analytics import history


def _raw(prices: dict[int, int], owned=(1, 2), bank=5):
    return {
        "current_event": 12,
        "bootstrap": {"elements": [
            {"id": pid, "web_name": f"P{pid}", "now_cost": cost, "selected_by_percent": "10.0",
             "transfers_in_event": 100, "transfers_out_event": 50}
            for pid, cost in prices.items()
        ]},
        "entry_picks": {"picks": [{"element": p} for p in owned],
                        "entry_history": {"bank": bank}},
    }


def test_first_snapshot_sums_my_players_plus_bank(tmp_path):
    values, prices = history.record_daily_snapshot(
        _raw({1: 100, 2: 55, 3: 45}), tmp_path, date(2026, 11, 20))
    row = values.iloc[0]
    assert row["squad_value"] == 15.5      # 10.0 + 5.5, player 3 not owned
    assert row["bank"] == 0.5
    assert row["team_value"] == 16.0
    assert row["value_change"] == 0
    assert len(prices) == 3


def test_next_day_appends_and_tracks_changes(tmp_path):
    history.record_daily_snapshot(_raw({1: 100, 2: 55, 3: 45}), tmp_path, date(2026, 11, 20))
    values, prices = history.record_daily_snapshot(
        _raw({1: 101, 2: 54, 3: 46}), tmp_path, date(2026, 11, 21))

    assert list(values["snapshot_date"]) == ["2026-11-20", "2026-11-21"]
    last = values.iloc[-1]
    assert last["team_value"] == 16.0          # +0.1 and -0.1 cancel out
    assert last["players_rising"] == 1 and last["players_falling"] == 1

    day2 = prices[prices["snapshot_date"] == "2026-11-21"].set_index("player_id")
    assert day2.loc[1, "price_change"] == 0.1
    assert day2.loc[2, "price_change"] == -0.1
    assert day2.loc[3, "price_change"] == 0.1

    moves = history.squad_price_moves(prices, _raw({1: 101, 2: 54, 3: 46})["bootstrap"])
    assert {m["web_name"] for m in moves} == {"P1", "P2"}   # only my players


def test_rerun_same_day_replaces_instead_of_duplicating(tmp_path):
    history.record_daily_snapshot(_raw({1: 100, 2: 55}), tmp_path, date(2026, 11, 20))
    history.record_daily_snapshot(_raw({1: 100, 2: 55}), tmp_path, date(2026, 11, 20))
    values = pd.read_csv(tmp_path / "fact_value_daily.csv")
    prices = pd.read_csv(tmp_path / "fact_price_daily.csv")
    assert len(values) == 1
    assert len(prices) == 2


def test_header_only_seed_file_is_accepted(tmp_path):
    (tmp_path / "fact_value_daily.csv").write_text(",".join(history.VALUE_COLUMNS) + "\n")
    (tmp_path / "fact_price_daily.csv").write_text(",".join(history.PRICE_COLUMNS) + "\n")
    values, _ = history.record_daily_snapshot(_raw({1: 100, 2: 55}), tmp_path, date(2026, 11, 20))
    assert len(values) == 1
