"""Sanity tests for the analysis layer — run with: pytest"""
import pandas as pd
import pytest

from fpl_analytics import metrics

SAMPLE_PLAYERS = pd.DataFrame([
    # cheap, in-form player should out-rank an expensive, out-of-form one
    {"id": 1, "web_name": "Budget", "team_name": "Team A", "position": "MID",
     "price_m": 4.5, "total_points": 60, "form": 6.0, "minutes": 450,
     "status": "a", "selected_by_percent": 3.0, "chance_of_playing_next_round": None},
    {"id": 2, "web_name": "Premium", "team_name": "Team B", "position": "MID",
     "price_m": 13.0, "total_points": 70, "form": 1.0, "minutes": 450,
     "status": "a", "selected_by_percent": 40.0, "chance_of_playing_next_round": None},
    # should be filtered out: too few minutes
    {"id": 3, "web_name": "Benchwarmer", "team_name": "Team C", "position": "MID",
     "price_m": 4.5, "total_points": 5, "form": 1.0, "minutes": 30,
     "status": "a", "selected_by_percent": 0.5, "chance_of_playing_next_round": None},
    # should be filtered out: unavailable
    {"id": 4, "web_name": "Injured", "team_name": "Team D", "position": "MID",
     "price_m": 7.0, "total_points": 50, "form": 5.0, "minutes": 400,
     "status": "i", "selected_by_percent": 15.0, "chance_of_playing_next_round": 0},
])


def test_points_per_million_computed_correctly():
    scored = metrics.add_value_score(SAMPLE_PLAYERS)
    budget_row = scored[scored["web_name"] == "Budget"].iloc[0]
    assert budget_row["points_per_million"] == pytest.approx(60 / 4.5, rel=1e-3)


def test_top_value_picks_filters_low_minutes_and_unavailable():
    picks = metrics.top_value_picks(SAMPLE_PLAYERS, top_n=10)
    names = set(picks["web_name"])
    assert "Benchwarmer" not in names  # under the minutes floor
    assert "Injured" not in names      # not status == "a"
    assert {"Budget", "Premium"} <= names


def test_cheap_in_form_player_beats_expensive_out_of_form_player():
    picks = metrics.top_value_picks(SAMPLE_PLAYERS, top_n=10)
    ranked_names = list(picks["web_name"])
    assert ranked_names.index("Budget") < ranked_names.index("Premium")


def test_differentials_respects_ownership_ceiling():
    diffs = metrics.differentials(SAMPLE_PLAYERS, max_ownership=10.0)
    assert "Premium" not in set(diffs["web_name"])  # 40% owned, not a differential
    assert "Budget" in set(diffs["web_name"])        # 3% owned


def test_injury_watch_only_lists_unavailable_players():
    watch = metrics.injury_watch(SAMPLE_PLAYERS)
    assert list(watch["web_name"]) == ["Injured"]
