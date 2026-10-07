"""Checks for the Power BI star-schema export — run with: pytest"""
import pandas as pd

from fpl_analytics import powerbi

LIVE = {
    1: {"elements": [
        {"id": 1, "stats": {"minutes": 90, "total_points": 10}},   # captain
        {"id": 2, "stats": {"minutes": 0, "total_points": 0}},     # starter who did not play
        {"id": 3, "stats": {"minutes": 90, "total_points": 6}},    # bench player who comes on
        {"id": 4, "stats": {"minutes": 90, "total_points": 8}},    # bench player who stays benched
    ]}
}


def _picks(subs):
    # slots 1-2 start, slots 12-13 are bench (slot numbers kept realistic)
    return {1: {
        "picks": [
            {"element": 1, "position": 1, "multiplier": 2, "is_captain": True, "is_vice_captain": False},
            {"element": 2, "position": 2, "multiplier": 1, "is_captain": False, "is_vice_captain": True},
            {"element": 3, "position": 12, "multiplier": 0, "is_captain": False, "is_vice_captain": False},
            {"element": 4, "position": 13, "multiplier": 0, "is_captain": False, "is_vice_captain": False},
        ],
        "automatic_subs": subs,
    }}


def test_captain_points_are_doubled():
    fact = powerbi.build_fact_player_gw(LIVE)
    squad = powerbi.build_fact_my_squad(_picks([]), fact)
    cap = squad[squad["player_id"] == 1].iloc[0]
    assert cap["points_counted"] == 20  # 10 pts x2


def test_bench_points_counted_as_wasted_when_not_subbed_on():
    fact = powerbi.build_fact_player_gw(LIVE)
    squad = powerbi.build_fact_my_squad(_picks([]), fact)
    bench = squad[squad["player_id"] == 4].iloc[0]
    assert bench["points_counted"] == 0
    assert bench["points_on_bench"] == 8


def test_automatic_sub_moves_points_from_bench_to_starting_xi():
    fact = powerbi.build_fact_player_gw(LIVE)
    subs = [{"element_in": 3, "element_out": 2}]
    squad = powerbi.build_fact_my_squad(_picks(subs), fact)
    subbed_in = squad[squad["player_id"] == 3].iloc[0]
    subbed_out = squad[squad["player_id"] == 2].iloc[0]
    assert subbed_in["started"] and subbed_in["points_counted"] == 6
    assert not subbed_out["started"]
    assert squad["points_counted"].sum() == 20 + 6  # captain + auto-sub


def test_fixtures_are_long_format_one_row_per_team():
    fixtures = [{"event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 2,
                 "team_a_difficulty": 4, "finished": True, "team_h_score": 3, "team_a_score": 1}]
    df = powerbi.build_fact_team_fixture(fixtures)
    assert len(df) == 2
    home = df[df["team_id"] == 1].iloc[0]
    away = df[df["team_id"] == 2].iloc[0]
    assert home["is_home"] and home["difficulty"] == 2 and home["goals_for"] == 3
    assert (not away["is_home"]) and away["difficulty"] == 4 and away["goals_against"] == 3


def test_unscheduled_fixtures_are_skipped():
    fixtures = [{"event": None, "team_h": 1, "team_a": 2}]
    assert powerbi.build_fact_team_fixture(fixtures).empty


def test_my_gw_reconciliation_column_present():
    fact = powerbi.build_fact_player_gw(LIVE)
    squad = powerbi.build_fact_my_squad(_picks([]), fact)
    history = pd.DataFrame([{"gameweek": 1, "points": 20}])
    out = powerbi.build_fact_my_gw(history, squad)
    assert out.loc[0, "calc_points"] == 20
    assert out.loc[0, "points_diff_vs_official"] == 0


def test_bench_boost_counts_bench_players():
    fact = powerbi.build_fact_player_gw(LIVE)
    picks = _picks([])
    for pick in picks[1]["picks"]:
        if pick["multiplier"] == 0:
            pick["multiplier"] = 1  # Bench Boost: everyone counts
    squad = powerbi.build_fact_my_squad(picks, fact)
    assert squad["points_on_bench"].sum() == 0
    assert squad["points_counted"].sum() == 20 + 0 + 6 + 8
