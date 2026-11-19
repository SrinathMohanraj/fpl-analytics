"""Checks for the mini-league rival tracker — run with: pytest"""
import json

import pandas as pd

from fpl_analytics import rivals

ME, RIVAL, THIRD = 100, 200, 300

BOOTSTRAP = {
    "teams": [{"id": 1, "short_name": "ARS"}, {"id": 2, "short_name": "MCI"}],
    "elements": [
        {"id": pid, "web_name": f"P{pid}", "team": 1 + pid % 2, "total_points": 10 * pid}
        for pid in range(1, 8)
    ],
}
LIVE_GW2 = {"elements": [{"id": pid, "stats": {"total_points": pid}} for pid in range(1, 8)]}


def _picks(ids, captain):
    return {"picks": [
        {"element": pid, "position": i + 1, "multiplier": 2 if pid == captain else 1,
         "is_captain": pid == captain}
        for i, pid in enumerate(ids)
    ]}


def _history(points, cost=0, chip_gw=None):
    total, current = 0, []
    for gw, pts in enumerate(points, start=1):
        total += pts - (cost if gw == 2 else 0)
        current.append({"event": gw, "points": pts, "total_points": total,
                        "event_transfers_cost": cost if gw == 2 else 0,
                        "points_on_bench": 1, "overall_rank": 1000 * gw})
    chips = [{"event": chip_gw, "name": "bboost"}] if chip_gw else []
    return {"current": current, "chips": chips}


LEAGUE_RAW = {
    "league": {"id": 77, "name": "Mates"},
    "members": [
        {"entry": ME, "entry_name": "Mine", "player_name": "Me", "rank": 1, "last_rank": 2,
         "total": 110, "event_total": 50},
        {"entry": RIVAL, "entry_name": "Theirs", "player_name": "Rival", "rank": 2, "last_rank": 1,
         "total": 100, "event_total": 30},
        {"entry": THIRD, "entry_name": "Third", "player_name": "Other", "rank": 3, "last_rank": 3,
         "total": 90, "event_total": 40},
    ],
    "histories": {
        ME: _history([60, 50]),
        RIVAL: _history([70, 34], cost=4, chip_gw=2),
        THIRD: _history([50, 40]),
    },
    "picks": {
        ME: _picks([1, 2, 3], captain=1),
        RIVAL: _picks([1, 4, 5], captain=4),
        THIRD: _picks([1, 4, 6], captain=1),
    },
}


def test_league_rank_is_rebuilt_each_gameweek():
    gw = rivals.build_fact_league_gw(LEAGUE_RAW, ME)
    gw1 = gw[gw["gameweek"] == 1].set_index("entry_id")["league_rank"]
    gw2 = gw[gw["gameweek"] == 2].set_index("entry_id")["league_rank"]
    assert gw1[RIVAL] == 1 and gw1[ME] == 2      # rival led after GW1 (70 vs 60)
    assert gw2[ME] == 1 and gw2[RIVAL] == 2      # I overtook in GW2 (110 vs 100)


def test_gap_to_me_and_transfer_hits():
    gw = rivals.build_fact_league_gw(LEAGUE_RAW, ME)
    row = gw[(gw["gameweek"] == 2) & (gw["entry_id"] == RIVAL)].iloc[0]
    assert row["gap_to_me"] == 10            # 110 - 100, positive = I'm ahead
    assert row["net_points"] == 30 and row["chip"] == "bboost"


def test_head_to_head_differentials_and_captain_swing():
    players = rivals._player_lookup(BOOTSTRAP, LIVE_GW2)
    h2h = rivals.head_to_head(LEAGUE_RAW["picks"][ME], LEAGUE_RAW["picks"][RIVAL], players)
    assert {r["player_id"] for r in h2h["mine_only"]} == {2, 3}
    assert {r["player_id"] for r in h2h["theirs_only"]} == {4, 5}
    assert h2h["shared"] == 1
    # player 1: I captained (x2), they didn't -> +1 pt swing to me
    assert h2h["multiplier_diffs"][0]["swing"] == 1
    # mine 2+3=5, theirs 4*2 (their captain) + 5 = 13, captain swing +1 -> -7
    assert h2h["gw_swing"] == 5 - 13 + 1


def test_league_ownership_flags_unique_and_template_players():
    players = rivals._player_lookup(BOOTSTRAP, LIVE_GW2)
    own = {r["player_id"]: r for r in rivals.league_ownership(LEAGUE_RAW["picks"], ME, players)}
    assert own[1]["owners"] == 3 and own[1]["captained_by"] == 2
    assert own[4]["owners"] == 2 and not own[4]["i_own"]
    assert own[2]["owners"] == 1 and own[2]["i_own"]


def test_default_league_is_smallest_private_one():
    entry = {"leagues": {"classic": [
        {"id": 314, "name": "Overall", "league_type": "s", "rank_count": 11_000_000},
        {"id": 9, "name": "Big private", "league_type": "x", "rank_count": 400},
        {"id": 8, "name": "Small private", "league_type": "x", "rank_count": 15},
    ]}}
    assert rivals.default_league_ids(entry) == [8]
    assert rivals.parse_league_ids("26756, 123") == [26756, 123]
    assert rivals.parse_league_ids("auto") == []
    # an invite code is skipped instead of crashing the whole refresh
    assert rivals.parse_league_ids("tozclr") == []
    assert rivals.parse_league_ids("tozclr, 26756") == [26756]


def test_run_writes_tables_and_keeps_older_gameweek_picks(tmp_path):
    old = rivals.build_fact_league_picks(LEAGUE_RAW, 1)
    old.to_csv(tmp_path / "fact_league_picks.csv", index=False)

    raw = {"current_event": 2, "bootstrap": BOOTSTRAP, "event_live": {2: LIVE_GW2},
           "entry": {"leagues": {"classic": []}}}
    out = tmp_path / "rivals.json"
    payload = rivals.run(raw, ME, [77], tmp_path, [out], fetcher=lambda *a: LEAGUE_RAW)

    picks = pd.read_csv(tmp_path / "fact_league_picks.csv")
    assert sorted(picks["gameweek"].unique()) == [1, 2]
    assert len(pd.read_csv(tmp_path / "dim_league_entry.csv")) == 3
    lg = json.loads(out.read_text())["leagues"][0]
    assert lg["my_rank"] == 1 and lg["rank_trend"][str(ME)] == [2, 1]
    assert payload["leagues"][0]["template_players_i_miss"][0]["player_id"] == 4
