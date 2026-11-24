"""Checks for the transfer suggester — run with: pytest"""
import json

import pandas as pd

from fpl_analytics import transfers

ME = 1702239

# 6 clubs, 6 players each: ids 1-36. element_type cycles GKP, DEF, DEF, MID, MID, FWD.
TYPES = [1, 2, 2, 3, 3, 4]


def _element(pid):
    team = (pid - 1) // 6 + 1
    etype = TYPES[(pid - 1) % 6]
    return {
        "id": pid, "web_name": f"P{pid}", "first_name": "F", "second_name": f"P{pid}",
        "team": team, "element_type": etype, "now_cost": 50 + pid, "cost_change_start": 2,
        "selected_by_percent": str(pid), "form": "1.0", "total_points": pid,
        "status": "a", "chance_of_playing_next_round": None,
        "transfers_in_event": 1000 * pid, "transfers_out_event": 500 * (37 - pid),
    }


BOOTSTRAP = {
    "teams": [{"id": t, "name": f"Team{t}", "short_name": f"T{t}", "strength": 3} for t in range(1, 7)],
    "elements": [_element(pid) for pid in range(1, 37)],
    "events": [{"id": g, "is_current": g == 3, "is_next": g == 4, "finished": g <= 3}
               for g in range(1, 8)],
}
FIXTURES = [{"event": g, "team_h": h, "team_a": h + 1, "team_h_difficulty": 3,
             "team_a_difficulty": 3, "kickoff_time": None, "finished": g <= 3}
            for g in range(1, 8) for h in (1, 3, 5)]
# higher id = more points, so the best players are the high ids
EVENT_LIVE = {g: {"elements": [{"id": pid, "stats": {"minutes": 90, "total_points": pid // 3,
                                                       "expected_goals": 0.01 * pid,
                                                       "expected_assists": 0.0}}
                               for pid in range(1, 37)]} for g in (1, 2, 3)}


def _picks(ids, captain, chip=None):
    return {"active_chip": chip, "entry_history": {"bank": 15},
            "picks": [{"element": pid, "position": i + 1,
                       "multiplier": (2 if pid == captain else 1) if i < 11 else 0,
                       "is_captain": pid == captain} for i, pid in enumerate(ids)]}


# my squad, 2 GKP / 5 DEF / 5 MID / 3 FWD, clubs 1-4 already have 3 players each
MY_IDS = [1, 2, 3, 8, 10, 14, 16, 20, 22, 17, 24, 7, 28, 30, 36]
MY_PICKS = _picks(MY_IDS, captain=22)

# top-10k sample: 4 managers, all own player 35 (captained by 3), half own 34
SAMPLE = {
    "gameweek": 3,
    "managers": [{"entry": e, "rank": e * 100} for e in (1, 2, 3, 4)],
    "picks": {
        1: _picks([35, 34, 33], captain=35),
        2: _picks([35, 34, 31], captain=35),
        3: _picks([35, 36, 33], captain=35),
        4: _picks([35, 36, 29], captain=36, chip="freehit"),
    },
    "transfers": {
        1: [{"event": 3, "element_in": 34, "element_out": 5}],
        2: [{"event": 3, "element_in": 34, "element_out": 11},
            {"event": 2, "element_in": 31, "element_out": 4}],
        3: [],
        4: [{"event": 3, "element_in": 29, "element_out": 6}],  # free hit: ignored
    },
    # table either side of rank 37,000: 2,000 ranks per 20 points = 100 ranks a point
    "around_me": [[{"rank": 35150, "total": 770}, {"rank": 38850, "total": 733}]],
}

RAW = {
    "bootstrap": BOOTSTRAP,
    "fixtures": FIXTURES,
    "event_live": EVENT_LIVE,
    "current_event": 3,
    "entry": {"summary_overall_rank": 37000, "summary_overall_points": 751},
    "entry_history": {"current": [{"event": 1, "event_transfers": 0},
                                  {"event": 2, "event_transfers": 0},
                                  {"event": 3, "event_transfers": 1}], "chips": []},
    "entry_picks": MY_PICKS,
    "entry_transfers": [],
}


def test_ownership_counts_eo_and_ignores_free_hit_transfers():
    own = transfers.build_ownership(SAMPLE, BOOTSTRAP, MY_PICKS).set_index("player_id")
    assert own.loc[35, "ownership"] == 1.0
    assert own.loc[35, "effective_ownership"] == 1.75      # captained by 3 of 4
    assert own.loc[34, "ownership"] == 0.5
    assert own.loc[34, "transfers_in"] == 2                 # GW3 moves only
    assert own.loc[31, "transfers_in"] == 0                 # GW2 move not counted
    assert own.loc[29, "transfers_in"] == 0                 # free hit ignored
    assert own.loc[22, "i_own"] and own.loc[22, "my_multiplier"] == 2
    assert own.loc[1, "i_own"] and own.loc[1, "owners"] == 0   # mine, nobody else's


def test_ranks_per_point_from_table_around_me():
    rows = SAMPLE["around_me"][0]
    assert transfers.ranks_per_point(rows, 37000) == 100.0
    assert transfers.ranks_per_point([], 37000) is None


def test_sample_pages_spread_over_top_10k():
    pages = transfers.sample_pages(10_000, 25)
    assert pages[0] == 1 and pages[-1] == 200 and len(pages) == 25


def test_selling_price_keeps_half_of_a_rise():
    picks = {"picks": [{"element": 10}, {"element": 11}]}
    bought = [{"element_in": 10, "element_in_cost": 55, "time": "2026-09-01"}]
    sell = transfers.selling_prices(picks, bought, BOOTSTRAP)
    assert sell[10] == 5.7          # paid 5.5, now 6.0 -> keep 0.2 of the 0.5 rise
    assert sell[11] == 6.0          # bought at start (5.9), now 6.1 -> 5.9 + 0.1


def test_free_transfers_roll_and_cap():
    hist = {"current": [{"event": g, "event_transfers": 0} for g in range(1, 9)], "chips": []}
    assert transfers.free_transfers_estimate(hist, 9) == 5
    hist["current"][7]["event_transfers"] = 2   # used 2 in GW8 with 5 banked
    assert transfers.free_transfers_estimate(hist, 9) == 4


def test_run_writes_csvs_and_payload(tmp_path):
    out = tmp_path / "transfers.json"
    payload = transfers.run(RAW, ME, tmp_path, [out], fetcher=lambda gw, rank: SAMPLE)

    assert out.exists() and json.loads(out.read_text())["sample_size"] == 4
    sug = pd.read_csv(tmp_path / "fact_transfer_suggestion.csv")
    assert not sug.empty
    assert list(sug.columns) == ["list"] + transfers.SUGGESTION_COLUMNS
    follow = sug[sug["list"] == "follow_top10k"]
    assert set(follow["in_player_id"]) == {34}          # the top 10k's buy
    assert [r["in_name"] for r in payload["follow_top10k"]] == list(follow["in_name"])
    sug = sug[sug["list"] == "best_points"]
    # every suggestion: same position, affordable, an upgrade, and the
    # rank change is points x 100 ranks a point
    for _, r in sug.iterrows():
        assert r["buy_price_m"] <= r["sell_price_m"] + 1.5 + 1e-9
        assert r["xp_gain"] > 0
        assert r["expected_rank_change"] == round(r["net_gain"] * 100)
        assert r["in_player_id"] not in MY_IDS
    pos = {e["id"]: e["element_type"] for e in BOOTSTRAP["elements"]}
    assert all(pos[a] == pos[b] for a, b in zip(sug["out_player_id"], sug["in_player_id"]))
    # no more than 3 from one club after the swap
    team = {e["id"]: e["team"] for e in BOOTSTRAP["elements"]}
    for _, r in sug.iterrows():
        squad = [p for p in MY_IDS if p != r["out_player_id"]] + [r["in_player_id"]]
        assert pd.Series([team[p] for p in squad]).value_counts().max() <= 3

    own = pd.read_csv(tmp_path / "fact_top10k_ownership.csv")
    assert set(own["gameweek"]) == {3}
    assert payload["me"]["ranks_per_point"] == 100.0
    assert payload["horizon"] == [4, 5, 6]
    assert payload["top10k_bought"][0]["web_name"] == "P34"
    assert payload["verdict"]


def test_ownership_history_keeps_older_gameweeks(tmp_path):
    path = tmp_path / "fact_top10k_ownership.csv"
    transfers.run(RAW, ME, tmp_path, [], fetcher=lambda gw, rank: {**SAMPLE, "gameweek": 2})
    transfers.run(RAW, ME, tmp_path, [], fetcher=lambda gw, rank: SAMPLE)
    once = len(pd.read_csv(path))
    transfers.run(RAW, ME, tmp_path, [], fetcher=lambda gw, rank: SAMPLE)  # same GW again
    own = pd.read_csv(path)
    assert sorted(own["gameweek"].unique()) == [2, 3]
    assert len(own) == once  # re-running a gameweek replaces its rows
