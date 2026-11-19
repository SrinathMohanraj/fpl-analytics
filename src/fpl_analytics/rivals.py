"""Mini-league rival tracker: me vs the other managers in my classic leagues.

For each tracked league this module pulls the standings, every member's
gameweek history, and every member's picks for the current gameweek, then
builds:

    dim_league_entry   one row per manager per league (names, rank, total)
    fact_league_gw     one row per manager per gameweek: points, total,
                       league rank that week, gap to me, chip, hits
    fact_league_picks  one row per player per manager per gameweek: who owned
                       whom and who they captained. The API only gives picks
                       for one gameweek per call, so each run saves the current
                       gameweek and keeps earlier gameweeks already on file.

plus a dashboard payload (rivals.json) with standings, the league-rank trend,
head-to-head differentials and league ownership.

Which leagues: pass league IDs (the number in the league's URL on
fantasy.premierleague.com/leagues/<id>/standings/c). With none given, the
smallest private classic league I am in is used. Big public leagues are cut
to the top MAX_MEMBERS managers (plus me).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import fetch

MAX_MEMBERS = 50          # one page of standings; keeps API calls bounded
UNIQUE_MAX_OWNERS = 2     # "only you or one other rival own him" = a league differential
TEMPLATE_MIN_SHARE = 0.5  # owned by at least half the league = a template player

DIM_COLUMNS = ["league_entry_key", "league_id", "league_name", "entry_id", "entry_name",
               "manager_name", "is_me", "league_rank", "last_rank", "total_points"]
GW_COLUMNS = ["league_entry_key", "league_id", "entry_id", "gameweek", "points",
              "transfer_cost", "net_points", "total_points", "points_on_bench",
              "overall_rank", "chip", "league_rank", "gap_to_me"]
PICK_COLUMNS = ["league_entry_key", "league_id", "entry_id", "gameweek", "player_id",
                "squad_slot", "is_starter", "is_captain", "multiplier"]


def _key(league_id: int, entry_id: int) -> str:
    return f"{league_id}-{entry_id}"


# ---- choosing leagues ---------------------------------------------------------

def parse_league_ids(value: str | None) -> list[int]:
    """'26756, 123' -> [26756, 123]. Empty / 'auto' -> [] (auto-pick)."""
    if not value or value.strip().lower() == "auto":
        return []
    return [int(v) for v in value.replace(";", ",").split(",") if v.strip()]


def my_classic_leagues(entry: dict) -> list[dict]:
    """Classic leagues from /entry/<id>/, as {id, name, private, rank, size}."""
    out = []
    for lg in entry.get("leagues", {}).get("classic", []):
        out.append({
            "id": lg["id"],
            "name": lg["name"],
            "private": lg.get("league_type") == "x",
            "rank": lg.get("entry_rank"),
            "size": lg.get("rank_count"),
        })
    return out


def default_league_ids(entry: dict) -> list[int]:
    """Smallest private league; if none, the smallest league of any kind."""
    leagues = my_classic_leagues(entry)
    private = [lg for lg in leagues if lg["private"]]
    pool = private or leagues
    if not pool:
        return []
    return [min(pool, key=lambda lg: lg["size"] or 10**9)["id"]]


# ---- fetching -----------------------------------------------------------------

def fetch_league(league_id: int, my_entry_id: int, gameweek: int) -> dict:
    """Standings + each member's history and current-gameweek picks."""
    standings = fetch.get_league_standings(league_id)
    members = standings["standings"]["results"][:MAX_MEMBERS]
    if all(m["entry"] != my_entry_id for m in members):
        mine = next((m for m in standings["standings"]["results"] if m["entry"] == my_entry_id), None)
        if mine:
            members.append(mine)

    histories, picks = {}, {}
    for m in members:
        eid = m["entry"]
        histories[eid] = fetch.get_entry_history(eid)
        try:
            picks[eid] = fetch.get_entry_picks(eid, gameweek)
        except RuntimeError:
            picks[eid] = None  # joined after this gameweek's deadline
    return {"league": standings["league"], "members": members,
            "histories": histories, "picks": picks}


# ---- tables -------------------------------------------------------------------

def build_dim_league_entry(league_raw: dict, my_entry_id: int) -> pd.DataFrame:
    lg = league_raw["league"]
    rows = [{
        "league_entry_key": _key(lg["id"], m["entry"]),
        "league_id": lg["id"],
        "league_name": lg["name"],
        "entry_id": m["entry"],
        "entry_name": m["entry_name"],
        "manager_name": m["player_name"],
        "is_me": m["entry"] == my_entry_id,
        "league_rank": m["rank"],
        "last_rank": m["last_rank"],
        "total_points": m["total"],
    } for m in league_raw["members"]]
    return pd.DataFrame(rows, columns=DIM_COLUMNS)


def build_fact_league_gw(league_raw: dict, my_entry_id: int) -> pd.DataFrame:
    """Per-gameweek history for each member, with the league table rebuilt each week.

    League rank per gameweek is worked out from cumulative points among the
    tracked members (ties share a rank), so it may differ slightly from FPL's
    own tie-breaks.
    """
    league_id = league_raw["league"]["id"]
    rows = []
    for eid, hist in league_raw["histories"].items():
        chips = {c["event"]: c["name"] for c in hist.get("chips", [])}
        for gw in hist.get("current", []):
            cost = gw.get("event_transfers_cost", 0)
            rows.append({
                "league_entry_key": _key(league_id, eid),
                "league_id": league_id,
                "entry_id": int(eid),
                "gameweek": gw["event"],
                "points": gw["points"],
                "transfer_cost": cost,
                "net_points": gw["points"] - cost,
                "total_points": gw["total_points"],
                "points_on_bench": gw.get("points_on_bench", 0),
                "overall_rank": gw.get("overall_rank"),
                "chip": chips.get(gw["event"], ""),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=GW_COLUMNS)
    df["league_rank"] = (df.groupby("gameweek")["total_points"]
                         .rank(method="min", ascending=False).astype(int))
    mine = df[df["entry_id"] == my_entry_id].set_index("gameweek")["total_points"]
    df["gap_to_me"] = df["gameweek"].map(mine) - df["total_points"]  # + = I'm ahead
    return df.sort_values(["gameweek", "league_rank", "entry_id"]).reset_index(drop=True)[GW_COLUMNS]


def build_fact_league_picks(league_raw: dict, gameweek: int) -> pd.DataFrame:
    league_id = league_raw["league"]["id"]
    rows = []
    for eid, payload in league_raw["picks"].items():
        if not payload:
            continue
        for p in payload["picks"]:
            rows.append({
                "league_entry_key": _key(league_id, eid),
                "league_id": league_id,
                "entry_id": int(eid),
                "gameweek": gameweek,
                "player_id": p["element"],
                "squad_slot": p["position"],
                "is_starter": p["position"] <= 11,
                "is_captain": bool(p["is_captain"]),
                "multiplier": p["multiplier"],
            })
    return pd.DataFrame(rows, columns=PICK_COLUMNS)


def _upsert_picks(path: Path, new: pd.DataFrame) -> pd.DataFrame:
    """Replace the rows for (league, gameweek) pairs in `new`; keep everything else."""
    if path.exists() and path.stat().st_size > 0:
        old = pd.read_csv(path)
        if not old.empty and not new.empty:
            replaced = set(zip(new["league_id"], new["gameweek"]))
            keep = [(lg, gw) not in replaced for lg, gw in zip(old["league_id"], old["gameweek"])]
            old = old[keep]
        if not old.empty:
            new = pd.concat([old, new], ignore_index=True) if not new.empty else old
    new = new.sort_values(["league_id", "gameweek", "entry_id", "squad_slot"]).reset_index(drop=True)
    return new[PICK_COLUMNS]


# ---- dashboard payload --------------------------------------------------------

def _player_lookup(bootstrap: dict, live_gw: dict | None) -> dict[int, dict]:
    teams = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    gw_pts = {}
    if live_gw:
        gw_pts = {e["id"]: e["stats"].get("total_points", 0) for e in live_gw.get("elements", [])}
    return {e["id"]: {"name": e["web_name"], "team": teams.get(e["team"], ""),
                      "season_points": e["total_points"], "gw_points": gw_pts.get(e["id"], 0)}
            for e in bootstrap["elements"]}


def _squad(picks: dict | None) -> dict[int, dict]:
    if not picks:
        return {}
    return {p["element"]: p for p in picks["picks"]}


def head_to_head(my_picks: dict | None, their_picks: dict | None, players: dict) -> dict:
    """Players only I own vs players only they own (starters count, bench shown too)."""
    mine, theirs = _squad(my_picks), _squad(their_picks)

    def row(pid: int, pick: dict) -> dict:
        p = players.get(pid, {"name": str(pid), "team": "", "gw_points": 0, "season_points": 0})
        mult = pick["multiplier"]
        return {"player_id": pid, "name": p["name"], "team": p["team"],
                "starter": pick["position"] <= 11, "captain": bool(pick["is_captain"]),
                "gw_points": p["gw_points"], "counted": p["gw_points"] * mult,
                "season_points": p["season_points"]}

    mine_only = [row(pid, pk) for pid, pk in mine.items() if pid not in theirs]
    theirs_only = [row(pid, pk) for pid, pk in theirs.items() if pid not in mine]
    # same player, different captaincy, is a differential too
    cap_swing = []
    for pid in set(mine) & set(theirs):
        if mine[pid]["multiplier"] != theirs[pid]["multiplier"]:
            p = players.get(pid, {"name": str(pid), "gw_points": 0})
            cap_swing.append({"name": p["name"], "my_multiplier": mine[pid]["multiplier"],
                              "their_multiplier": theirs[pid]["multiplier"],
                              "swing": p["gw_points"] * (mine[pid]["multiplier"] - theirs[pid]["multiplier"])})
    key = lambda r: (not r["starter"], -r["season_points"])  # noqa: E731
    return {
        "mine_only": sorted(mine_only, key=key),
        "theirs_only": sorted(theirs_only, key=key),
        "multiplier_diffs": cap_swing,
        "shared": len(set(mine) & set(theirs)),
        "gw_swing": sum(r["counted"] for r in mine_only) - sum(r["counted"] for r in theirs_only)
                    + sum(c["swing"] for c in cap_swing),
    }


def league_ownership(picks_by_entry: dict, my_entry_id: int, players: dict) -> list[dict]:
    """How many tracked managers own each player (whole 15-man squads)."""
    squads = {eid: set(_squad(p)) for eid, p in picks_by_entry.items() if p}
    n = len(squads)
    if not n:
        return []
    counts: dict[int, int] = {}
    captains: dict[int, int] = {}
    for eid, p in picks_by_entry.items():
        if not p:
            continue
        for pk in p["picks"]:
            counts[pk["element"]] = counts.get(pk["element"], 0) + 1
            if pk["is_captain"]:
                captains[pk["element"]] = captains.get(pk["element"], 0) + 1
    mine = squads.get(my_entry_id, set())
    rows = []
    for pid, c in counts.items():
        p = players.get(pid, {"name": str(pid), "team": "", "season_points": 0, "gw_points": 0})
        rows.append({"player_id": pid, "name": p["name"], "team": p["team"],
                     "owners": c, "share": round(c / n, 3), "captained_by": captains.get(pid, 0),
                     "i_own": pid in mine, "season_points": p["season_points"],
                     "gw_points": p["gw_points"]})
    return sorted(rows, key=lambda r: (-r["owners"], -r["season_points"]))


def build_league_payload(league_raw: dict, my_entry_id: int, gameweek: int,
                         bootstrap: dict, live_gw: dict | None,
                         fact_gw: pd.DataFrame) -> dict:
    players = _player_lookup(bootstrap, live_gw)
    lg = league_raw["league"]
    picks = league_raw["picks"]
    my_picks = picks.get(my_entry_id)
    latest = fact_gw[fact_gw["gameweek"] == fact_gw["gameweek"].max()] if not fact_gw.empty else fact_gw
    latest = latest.set_index("entry_id") if not latest.empty else latest

    members = []
    for m in sorted(league_raw["members"], key=lambda m: m["rank"]):
        eid = m["entry"]
        hist_row = latest.loc[eid] if not latest.empty and eid in latest.index else None
        cap = next((pk["element"] for pk in (picks.get(eid) or {}).get("picks", []) if pk["is_captain"]), None)
        members.append({
            "entry_id": eid,
            "entry_name": m["entry_name"],
            "manager_name": m["player_name"],
            "is_me": eid == my_entry_id,
            "rank": m["rank"],
            "last_rank": m["last_rank"],
            "total": m["total"],
            "gw_points": m["event_total"],
            "gap_to_me": None if hist_row is None else int(hist_row["gap_to_me"]) if pd.notna(hist_row["gap_to_me"]) else None,
            "transfer_cost": None if hist_row is None else int(hist_row["transfer_cost"]),
            "chip": "" if hist_row is None else hist_row["chip"],
            "captain": players.get(cap, {}).get("name") if cap else None,
            "head_to_head": None if eid == my_entry_id else head_to_head(my_picks, picks.get(eid), players),
        })

    trend: dict[str, list] = {}
    gws = sorted(fact_gw["gameweek"].unique().tolist()) if not fact_gw.empty else []
    for eid, grp in fact_gw.groupby("entry_id"):
        by_gw = dict(zip(grp["gameweek"], grp["league_rank"]))
        trend[str(eid)] = [int(by_gw[g]) if g in by_gw else None for g in gws]

    own = league_ownership(picks, my_entry_id, players)
    n = sum(1 for p in picks.values() if p)
    my_unique = [r for r in own if r["i_own"] and r["owners"] <= UNIQUE_MAX_OWNERS and n > 2]
    missing = [r for r in own if not r["i_own"] and r["share"] >= TEMPLATE_MIN_SHARE]

    me = next((m for m in members if m["is_me"]), None)
    return {
        "league_id": lg["id"],
        "league_name": lg["name"],
        "size": len(members),
        "my_rank": me["rank"] if me else None,
        "members": members,
        "gameweeks": [int(g) for g in gws],
        "rank_trend": trend,
        "my_unique_players": my_unique,
        "template_players_i_miss": missing,
        "league_captains": sorted(
            [{"name": r["name"], "count": r["captained_by"]} for r in own if r["captained_by"]],
            key=lambda r: -r["count"]),
    }


# ---- orchestration ------------------------------------------------------------

def run(raw: dict, my_entry_id: int, league_ids: list[int], powerbi_dir: Path,
        out_paths: list[Path], fetcher=fetch_league) -> dict:
    """Fetch, build tables, write CSVs + rivals.json. Returns the payload."""
    gameweek = int(raw["current_event"])
    leagues_available = my_classic_leagues(raw["entry"])
    ids = league_ids or default_league_ids(raw["entry"])
    live_gw = (raw.get("event_live") or {}).get(gameweek)

    dims, gws, picks, payloads = [], [], [], []
    for lid in ids:
        league_raw = fetcher(lid, my_entry_id, gameweek)
        dim = build_dim_league_entry(league_raw, my_entry_id)
        fact_gw = build_fact_league_gw(league_raw, my_entry_id)
        dims.append(dim)
        gws.append(fact_gw)
        picks.append(build_fact_league_picks(league_raw, gameweek))
        payloads.append(build_league_payload(league_raw, my_entry_id, gameweek,
                                             raw["bootstrap"], live_gw, fact_gw))

    powerbi_dir.mkdir(parents=True, exist_ok=True)
    cat = lambda frames, cols: (pd.concat(frames, ignore_index=True)  # noqa: E731
                                if frames else pd.DataFrame(columns=cols))
    cat(dims, DIM_COLUMNS).to_csv(powerbi_dir / "dim_league_entry.csv", index=False, encoding="utf-8")
    cat(gws, GW_COLUMNS).to_csv(powerbi_dir / "fact_league_gw.csv", index=False, encoding="utf-8")
    picks_path = powerbi_dir / "fact_league_picks.csv"
    all_picks = _upsert_picks(picks_path, cat(picks, PICK_COLUMNS))
    # only keep history for leagues still tracked
    all_picks = all_picks[all_picks["league_id"].isin(ids)]
    all_picks.to_csv(picks_path, index=False, encoding="utf-8")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entry_id": my_entry_id,
        "current_gameweek": gameweek,
        "available_leagues": leagues_available,
        "leagues": payloads,
    }
    text = json.dumps(payload, indent=2, default=str)
    for p in out_paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return payload
