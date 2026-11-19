"""Checks for the captain picker — run with: pytest"""
import pandas as pd

from fpl_analytics import captain


def _tables():
    # two forwards on different teams; player 1 is better on paper,
    # but in GW3 player 1's team has no fixture (a blank gameweek)
    gw_rows = []
    for gw in (1, 2):
        gw_rows.append({"player_id": 1, "gameweek": gw, "minutes": 90, "total_points": 10,
                        "expected_goals": 0.8, "expected_assists": 0.2})
        gw_rows.append({"player_id": 2, "gameweek": gw, "minutes": 90, "total_points": 4,
                        "expected_goals": 0.3, "expected_assists": 0.1})
    # GW3 results (the picker must not see these when scoring GW3)
    gw_rows.append({"player_id": 1, "gameweek": 3, "minutes": 0, "total_points": 0,
                    "expected_goals": 0, "expected_assists": 0})
    gw_rows.append({"player_id": 2, "gameweek": 3, "minutes": 90, "total_points": 12,
                    "expected_goals": 1, "expected_assists": 0})
    fixtures = pd.DataFrame([
        {"gameweek": gw, "team_id": t, "opponent_id": 3 - t, "is_home": t == 1, "difficulty": 3}
        for gw in (1, 2, 4) for t in (1, 2)
    ] + [{"gameweek": 3, "team_id": 2, "opponent_id": 9, "is_home": True, "difficulty": 2}])
    squad = pd.DataFrame([
        {"gameweek": 3, "player_id": 1, "squad_slot": 1, "is_captain": True, "player_points": 0.0},
        {"gameweek": 3, "player_id": 2, "squad_slot": 2, "is_captain": False, "player_points": 12.0},
    ])
    return {
        "fact_player_gw": pd.DataFrame(gw_rows),
        "fact_team_fixture": fixtures,
        "dim_player": pd.DataFrame({"player_id": [1, 2], "web_name": ["Star", "Steady"],
                                    "team_id": [1, 2], "position": ["FWD", "FWD"]}),
        "dim_team": pd.DataFrame({"team_id": [1, 2, 9], "short_name": ["AAA", "BBB", "ZZZ"]}),
        "fact_my_squad": squad,
    }


def test_better_player_ranks_first_with_a_normal_fixture():
    ranked = captain.rank_squad(_tables(), [1, 2], gameweek=4)
    assert list(ranked["web_name"]) == ["Star", "Steady"]
    assert ranked["reason"].str.len().gt(0).all()


def test_blank_gameweek_scores_zero():
    ranked = captain.rank_squad(_tables(), [1, 2], gameweek=3)
    assert ranked.iloc[0]["web_name"] == "Steady"
    star = ranked[ranked["web_name"] == "Star"].iloc[0]
    assert star["expected_points"] == 0
    assert star["reason"] == "No fixture this gameweek"


def test_injury_flag_drops_a_player():
    ranked = captain.rank_squad(_tables(), [1, 2], gameweek=4, availability={1: 0.0})
    assert ranked.iloc[0]["web_name"] == "Steady"


def test_backtest_compares_against_my_captain_without_peeking():
    bt = captain.backtest(_tables(), first_gw=3)
    row = bt.iloc[0]
    assert row["picker_captain"] == "Steady"      # Star had no fixture in GW3
    assert row["my_captain"] == "Star"
    assert row["picker_vs_me"] == 12
    summary = captain.backtest_summary(bt)
    assert summary["picker_gain"] == 12 and summary["picker_hits"] == 1
