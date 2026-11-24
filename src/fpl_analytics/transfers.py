"""Transfer suggester: what the top 10k are doing, and what a transfer does to my rank.

Three questions, one module:

1. What are the top 10k managers transferring?
   A sample of managers spread evenly across ranks 1-10,000 of the Overall
   league (FPL league 314). For each one we read their squad for the current
   gameweek and the transfers they made for it. That gives top-10k ownership,
   effective ownership (EO: captains count twice, benched players zero) and the
   most bought and sold players. FPL's own all-manager numbers
   (selected_by_percent, transfers_in_event) sit next to them for comparison.

2. Who should I bring in?
   Every player in my squad is paired with every affordable replacement in the
   same position (my bank plus his estimated selling price, max 3 per club).
   Both are scored with the captain picker's expected-points model over the
   next HORIZON gameweeks, and the gain is what my best XI gains each week
   (so upgrading a bench player who would rarely play is worth little).

3. What would the transfer do to my rank?
   - Expected effect: the points gained x "ranks per point" around my current
     overall rank (read from the Overall league table either side of me).
     Ownership does not change the *expected* effect: the field scores what it
     scores whether I make the transfer or not.
   - Risk: ownership changes how much a haul moves me. If a player the top 10k
     own (EO 90%) hauls and I don't have him, I lose about 0.9 x his points
     against them. So each suggestion shows the rank risk it removes (buying a
     high-EO player = a "shield") and the risk it adds (selling one), using a
     HAUL_POINTS haul.

Outputs:
    data/powerbi/fact_top10k_ownership.csv    one row per player per gameweek
                                              (kept for past gameweeks)
    data/powerbi/fact_transfer_suggestion.csv  the ranked transfer ideas
    dashboard/data/transfers.json              the dashboard panel's data

Notes and limits:
- Transfers made for the next deadline are private until it passes, so the
  top-10k moves are those made for the current gameweek (the last deadline).
- Selling prices are estimated from my transfer history and FPL's price
  change since the season start (you keep half of any rise, rounded down).
- Free transfers are estimated from my gameweek history (1 a week, up to 5
  banked; wildcard and free hit weeks keep them).
"""
from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from . import captain, fetch, powerbi

OVERALL_LEAGUE_ID = 314   # FPL's "Overall" league: every manager
TOP_N = 10_000            # the group we compare against
PAGE_SIZE = 50            # managers per standings page
SAMPLE_PAGES = 25         # standings pages read, spread evenly over ranks 1..TOP_N
PER_PAGE = 16             # managers sampled from each page -> 400 managers
WORKERS = 6               # parallel API calls (kept low to be polite to FPL)

HORIZON = 3               # gameweeks of expected points a transfer is judged on
HIT_COST = 4              # points for each transfer beyond the free ones
MAX_FREE_TRANSFERS = 5
HAUL_POINTS = 12          # "if he hauls" scenario used for rank risk
SHIELD_EO = 0.5           # top-10k EO at or above this = following the crowd
DIFFERENTIAL_EO = 0.10    # below this = a differential
MIN_GAIN = 0.5            # ignore swaps worth less than this over the horizon
MAX_PER_OUT = 3           # suggestions kept per player sold
MAX_SUGGESTIONS = 15
THREAT_EO = 0.30          # template players I don't own, shown as rank threats

OWNERSHIP_COLUMNS = [
    "gameweek", "player_id", "web_name", "team", "position", "price_m",
    "sample_size", "owners", "ownership", "effective_ownership", "captain_share",
    "transfers_in", "transfers_out", "net_transfers", "net_transfers_share",
    "overall_ownership", "i_own", "my_multiplier",
]
SUGGESTION_COLUMNS = [
    "rank", "next_gameweek", "horizon_gws", "out_player_id", "out_name", "in_player_id",
    "in_name", "position", "in_team", "sell_price_m", "buy_price_m", "bank_after_m",
    "xp_out", "xp_in", "xp_gain", "hit_cost", "net_gain", "ranks_per_point",
    "expected_rank_change", "eo_out", "eo_in", "own_in_top10k", "own_in_overall",
    "top10k_net_transfers_share", "risk_added_ranks", "risk_removed_ranks", "style",
    "fixtures_in", "reason",
]


# ---- fetching -----------------------------------------------------------------

def sample_pages(top_n: int = TOP_N, pages: int = SAMPLE_PAGES) -> list[int]:
    """Standings page numbers spread evenly from page 1 to the page holding rank top_n."""
    last = max(1, math.ceil(top_n / PAGE_SIZE))
    if pages >= last:
        return list(range(1, last + 1))
    step = (last - 1) / (pages - 1)
    return sorted({1 + round(i * step) for i in range(pages)})


def _spread(rows: list, k: int) -> list:
    """k rows evenly spaced through `rows` (all of them if there are fewer)."""
    if len(rows) <= k:
        return rows
    step = len(rows) / k
    return [rows[int(i * step)] for i in range(k)]


def _parallel(fn, items, workers: int = WORKERS) -> list:
    """fn(item) for each item, a few at a time; a failed call gives None."""
    def safe(item):
        try:
            return fn(item)
        except Exception:  # noqa: BLE001 - one missing manager shouldn't stop the run
            return None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(safe, items))


def _rank_page(rank: int) -> int:
    return max(1, (rank - 1) // PAGE_SIZE + 1)


def fetch_top_sample(gameweek: int, my_rank: int | None) -> dict:
    """Sample of top-10k managers (squad + transfers) and the table around my rank."""
    pages = sample_pages()
    standings = _parallel(lambda p: fetch.get_league_standings(OVERALL_LEAGUE_ID, p), pages)
    managers = []
    for page in standings:
        if page:
            managers += _spread(page["standings"]["results"], PER_PAGE)
    managers = [m for m in managers if m["rank"] <= TOP_N]

    ids = [m["entry"] for m in managers]
    picks = _parallel(lambda e: fetch.get_entry_picks(e, gameweek), ids)
    transfers = _parallel(fetch.get_entry_transfers, ids)

    # two table pages either side of my rank, to read how many ranks a point is worth
    around = {}
    if my_rank:
        for r in rank_probe_ranks(my_rank):
            page = _rank_page(r)
            if page not in around:
                around[page] = _parallel(
                    lambda p: fetch.get_league_standings(OVERALL_LEAGUE_ID, p), [page])[0]
    return {
        "gameweek": gameweek,
        "managers": managers,
        "picks": dict(zip(ids, picks)),
        "transfers": dict(zip(ids, transfers)),
        "around_me": [p["standings"]["results"] for p in around.values() if p],
        "top_pages": [p["standings"]["results"] for p in standings if p],
    }


# ---- top-10k ownership and transfers -------------------------------------------

def build_ownership(sample: dict, bootstrap: dict, my_picks: dict | None) -> pd.DataFrame:
    """One row per player owned by anyone in the sample (or by me)."""
    gameweek = sample["gameweek"]
    counts: dict[int, dict] = {}

    def row(pid):
        return counts.setdefault(pid, {"owners": 0, "eo": 0, "captains": 0, "t_in": 0, "t_out": 0})

    n = 0
    for eid, p in sample["picks"].items():
        if not p:
            continue
        n += 1
        for pk in p["picks"]:
            r = row(pk["element"])
            r["owners"] += 1
            r["eo"] += pk["multiplier"]
            r["captains"] += int(bool(pk["is_captain"]))
        # a free hit squad is temporary, so its transfers aren't real moves
        if p.get("active_chip") == "freehit":
            continue
        for t in sample["transfers"].get(eid) or []:
            if t.get("event") == gameweek:
                row(t["element_in"])["t_in"] += 1
                row(t["element_out"])["t_out"] += 1

    mine = {pk["element"]: pk["multiplier"] for pk in (my_picks or {}).get("picks", [])}
    for pid in mine:
        row(pid)

    teams = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    elements = {e["id"]: e for e in bootstrap["elements"]}
    rows = []
    for pid, c in counts.items():
        e = elements.get(pid, {})
        rows.append({
            "gameweek": gameweek,
            "player_id": pid,
            "web_name": e.get("web_name", str(pid)),
            "team": teams.get(e.get("team"), ""),
            "position": powerbi.POSITION_MAP.get(e.get("element_type"), ""),
            "price_m": e.get("now_cost", 0) / 10,
            "sample_size": n,
            "owners": c["owners"],
            "ownership": round(c["owners"] / n, 4) if n else 0.0,
            "effective_ownership": round(c["eo"] / n, 4) if n else 0.0,
            "captain_share": round(c["captains"] / n, 4) if n else 0.0,
            "transfers_in": c["t_in"],
            "transfers_out": c["t_out"],
            "net_transfers": c["t_in"] - c["t_out"],
            "net_transfers_share": round((c["t_in"] - c["t_out"]) / n, 4) if n else 0.0,
            "overall_ownership": round(float(e.get("selected_by_percent") or 0) / 100, 4),
            "i_own": pid in mine,
            "my_multiplier": mine.get(pid, 0),
        })
    df = pd.DataFrame(rows, columns=OWNERSHIP_COLUMNS)
    return df.sort_values(["effective_ownership", "owners"], ascending=False).reset_index(drop=True)


def rank_probe_ranks(my_rank: int) -> tuple[int, int]:
    """Two ranks either side of mine (5% away, at least 500 places)."""
    delta = max(500, int(my_rank * 0.05))
    return max(1, my_rank - delta), my_rank + delta


def ranks_per_point(rows: list[dict], my_rank: int | None) -> float | None:
    """How many overall ranks one point is worth near my rank.

    Takes the table rows nearest to the two probe ranks and divides the rank
    gap by the points gap. None if the rows don't give a usable gap.
    """
    rows = [r for r in rows if r.get("rank") and r.get("total") is not None]
    if not my_rank or len(rows) < 2:
        return None
    lo, hi = rank_probe_ranks(my_rank)
    a = min(rows, key=lambda r: abs(r["rank"] - lo))
    b = min(rows, key=lambda r: abs(r["rank"] - hi))
    d_rank, d_pts = b["rank"] - a["rank"], a["total"] - b["total"]
    if d_rank <= 0 or d_pts <= 0:
        return None
    return round(d_rank / d_pts, 1)


# ---- my squad: budget, free transfers ----------------------------------------

def selling_prices(entry_picks: dict, entry_transfers: list, bootstrap: dict) -> dict[int, float]:
    """player_id -> estimated selling price (£m) for my current squad.

    Purchase price = what I paid in my latest transfer for him, else his
    season-start price. FPL gives back half of any rise (rounded down to
    £0.1m) and all of any fall.
    """
    elements = {e["id"]: e for e in bootstrap["elements"]}
    bought: dict[int, int] = {}
    for t in sorted(entry_transfers or [], key=lambda t: t.get("time") or ""):
        bought[t["element_in"]] = t["element_in_cost"]
    out = {}
    for pk in entry_picks["picks"]:
        pid = pk["element"]
        e = elements.get(pid, {})
        now = e.get("now_cost", 0)
        paid = bought.get(pid, now - e.get("cost_change_start", 0))
        sell = paid + (now - paid) // 2 if now > paid else now
        out[pid] = sell / 10
    return out


def free_transfers_estimate(entry_history: dict, next_gw: int | None) -> int:
    """Free transfers I'm likely to have for next_gw (FPL doesn't publish it)."""
    chips = {c["event"]: c["name"] for c in entry_history.get("chips", [])}
    made = {g["event"]: g.get("event_transfers", 0) for g in entry_history.get("current", [])}
    if not made:
        return 1
    ft = 1  # for GW2 (GW1 squads are free to build)
    first = min(made) + 1
    for gw in range(first, (next_gw or max(made) + 1)):
        if gw in made:
            if chips.get(gw) in ("wildcard", "freehit"):
                ft = min(MAX_FREE_TRANSFERS, ft + 1)
            else:
                ft = min(MAX_FREE_TRANSFERS, max(0, ft - made[gw]) + 1)
        else:
            ft = min(MAX_FREE_TRANSFERS, ft + 1)
    return ft


# ---- expected points ----------------------------------------------------------

def availability_from_bootstrap(bootstrap: dict) -> dict[int, float]:
    out = {}
    for e in bootstrap["elements"]:
        chance = e.get("chance_of_playing_next_round")
        out[e["id"]] = (chance / 100 if chance is not None
                        else captain.STATUS_AVAILABILITY.get(e.get("status"), 1.0))
    return out


def project_points(tables: dict, gameweeks: list[int], availability: dict | None) -> pd.DataFrame:
    """Expected points per player summed over `gameweeks` (captain picker model)."""
    total, first, per_gw = None, None, {}
    for gw in gameweeks:
        df = captain.score_players(tables["fact_player_gw"], tables["fact_team_fixture"],
                                   tables["dim_player"], tables["dim_team"], gw,
                                   availability=availability)
        df = df.set_index("player_id")
        per_gw[gw] = df["expected_points"]
        if total is None:
            total, first = df["expected_points"].copy(), df
        else:
            total = total.add(df["expected_points"], fill_value=0)
    out = first[["web_name", "team_id", "position", "fixtures", "season_ppg", "form",
                 "minutes_security", "availability"]].copy()
    out["xp"] = total.round(2)
    out["xp_next"] = first["expected_points"]
    for gw, xp in per_gw.items():
        out[f"xp_gw{gw}"] = xp
    return out.reset_index()


# ---- best XI ------------------------------------------------------------------

FORMATION_MIN = {"GKP": 1, "DEF": 3, "MID": 2, "FWD": 1}
BENCH_WEIGHT = 0.1        # bench points rarely count; a little value for cover


def best_xi_points(players: list[tuple[str, float]]) -> float:
    """Expected points of the best legal XI from a 15-man squad, plus a little
    for the bench (1 keeper, at least 3 DEF / 2 MID / 1 FWD, 11 players)."""
    by_pos: dict[str, list[float]] = {}
    for pos, xp in players:
        by_pos.setdefault(pos, []).append(xp)
    for v in by_pos.values():
        v.sort(reverse=True)
    xi, rest = [], []
    for pos, need in FORMATION_MIN.items():
        got = by_pos.get(pos, [])
        xi += got[:need]
        if pos != "GKP":
            rest += got[need:]
    rest.sort(reverse=True)
    xi += rest[:11 - len(xi)]
    bench = sum(x for _, x in players) - sum(xi)
    return sum(xi) + BENCH_WEIGHT * bench


def squad_points(p: pd.DataFrame, squad: list[int], horizon: list[int]) -> float:
    """Best-XI expected points summed over the horizon gameweeks."""
    rows = p.loc[[s for s in squad if s in p.index]]
    return sum(best_xi_points(list(zip(rows["position"], rows[f"xp_gw{g}"]))) for g in horizon)


# ---- suggestions --------------------------------------------------------------

def _style(eo_in: float) -> str:
    if eo_in >= SHIELD_EO:
        return "Shield"
    if eo_in < DIFFERENTIAL_EO:
        return "Differential"
    return "Balanced"


def _ranks(points: float, rpp: float | None) -> int | None:
    return None if rpp is None else int(round(points * rpp))


def suggest(proj: pd.DataFrame, ownership: pd.DataFrame, players: pd.DataFrame,
            my_picks: dict, sell: dict[int, float], bank: float, free_transfers: int,
            rpp: float | None, next_gw: int | None, horizon: list[int],
            only_in: set[int] | None = None, min_gain: float = MIN_GAIN,
            per_out: int = MAX_PER_OUT) -> pd.DataFrame:
    """Best single transfers, ranked by expected points gained (after any hit).

    `only_in` limits who can come in (used for "follow the top 10k").
    """
    eo = ownership.set_index("player_id")["effective_ownership"].to_dict()
    own = ownership.set_index("player_id")["ownership"].to_dict()
    net = ownership.set_index("player_id")["net_transfers_share"].to_dict()
    overall = (players.set_index("player_id")["selected_by_percent"].fillna(0) / 100).to_dict()
    price = players.set_index("player_id")["price_m"].to_dict()
    team_short = players.set_index("player_id")["team"].to_dict()

    squad = [pk["element"] for pk in my_picks["picks"]]
    p = proj.set_index("player_id")
    club_count = p.loc[[s for s in squad if s in p.index], "team_id"].value_counts().to_dict()
    hit = 0 if free_transfers >= 1 else HIT_COST

    base = squad_points(p, squad, horizon)
    pool = p[~p.index.isin(squad) & (p["availability"] > 0.5) & (p["xp"] > 0)]
    if only_in is not None:
        pool = pool[pool.index.isin(only_in)]
    rows = []
    for out_id in squad:
        if out_id not in p.index:
            continue
        o = p.loc[out_id]
        budget = round(bank + sell.get(out_id, price.get(out_id, 0)), 1)
        cands = pool[(pool["position"] == o["position"])]
        affordable = pd.Series([price.get(i, 99) <= budget + 1e-9 for i in cands.index],
                               index=cands.index, dtype=bool)
        club_ok = pd.Series([club_count.get(t, 0) - (t == o["team_id"]) < 3 for t in cands["team_id"]],
                            index=cands.index, dtype=bool)
        cands = cands[affordable & club_ok]
        # the player's own gain is an upper bound on what my XI gains
        cands = cands[cands["xp"] - o["xp"] >= min_gain]
        others = [s for s in squad if s != out_id]
        xi_gain = pd.Series([squad_points(p, others + [i], horizon) - base for i in cands.index],
                            index=cands.index, dtype=float)
        cands = cands.assign(xi_gain=xi_gain)
        cands = cands[cands["xi_gain"] >= min_gain].sort_values("xi_gain", ascending=False)
        for in_id, c in cands.head(per_out).iterrows():
            gain = round(float(c["xi_gain"]), 2)
            eo_in, eo_out = float(eo.get(in_id, 0.0)), float(eo.get(out_id, 0.0))
            net_gain = round(gain - hit, 2)
            reason = [f"{c['xp']:.1f} vs {o['xp']:.1f} expected pts over GW{horizon[0]}-{horizon[-1]}"]
            if gain < float(c["xp"] - o["xp"]) - 0.5:
                reason.append("only part of that reaches my XI (bench cover)")
            if own.get(in_id, 0) > 0:
                reason.append(f"top 10k: {own[in_id]:.0%} own, EO {eo_in:.0%}")
            else:
                reason.append("no one in the top-10k sample owns him")
            if abs(net.get(in_id, 0)) >= 0.01:
                reason.append(f"{'bought' if net[in_id] > 0 else 'sold'} by "
                              f"{abs(net[in_id]):.0%} of the top 10k last deadline")
            if c["availability"] < 1:
                reason.append("injury doubt")
            rows.append({
                "next_gameweek": next_gw,
                "horizon_gws": len(horizon),
                "out_player_id": int(out_id),
                "out_name": o["web_name"],
                "in_player_id": int(in_id),
                "in_name": c["web_name"],
                "position": c["position"],
                "in_team": team_short.get(in_id, ""),
                "sell_price_m": sell.get(out_id, price.get(out_id)),
                "buy_price_m": price.get(in_id),
                "bank_after_m": round(budget - price.get(in_id, 0), 1),
                "xp_out": round(float(o["xp"]), 2),
                "xp_in": round(float(c["xp"]), 2),
                "xp_gain": gain,
                "hit_cost": hit,
                "net_gain": net_gain,
                "ranks_per_point": rpp,
                "expected_rank_change": _ranks(net_gain, rpp),
                "eo_out": round(eo_out, 3),
                "eo_in": round(eo_in, 3),
                "own_in_top10k": round(float(own.get(in_id, 0.0)), 3),
                "own_in_overall": round(float(overall.get(in_id, 0.0)), 3),
                "top10k_net_transfers_share": round(float(net.get(in_id, 0.0)), 3),
                # selling a player the top 10k own: if he hauls, I drop
                "risk_added_ranks": _ranks(HAUL_POINTS * eo_out, rpp),
                # buying one they own: his haul no longer hurts me
                "risk_removed_ranks": _ranks(HAUL_POINTS * eo_in, rpp),
                "style": _style(eo_in),
                "fixtures_in": c["fixtures"],
                "reason": "; ".join(reason),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=SUGGESTION_COLUMNS)
    df = df.sort_values(["net_gain", "eo_in"], ascending=False)
    # one row per player coming in (for the main list: his best swap), so the
    # list shows different options rather than one player three times
    df = df.drop_duplicates("in_player_id")
    df = df.head(MAX_SUGGESTIONS)
    df.insert(0, "rank", range(1, len(df) + 1))
    return df.reset_index(drop=True)[SUGGESTION_COLUMNS]


def _upsert_gameweek(path: Path, new: pd.DataFrame) -> pd.DataFrame:
    """Replace rows for the gameweeks in `new`; keep earlier gameweeks."""
    if path.exists() and path.stat().st_size > 0:
        old = pd.read_csv(path)
        old = old[~old["gameweek"].isin(new["gameweek"].unique())]
        if not old.empty:
            new = pd.concat([old, new], ignore_index=True)
    return new.sort_values(["gameweek", "effective_ownership"],
                           ascending=[True, False]).reset_index(drop=True)[OWNERSHIP_COLUMNS]


# ---- dashboard payload --------------------------------------------------------

def _records(df: pd.DataFrame, cols: list[str], n: int) -> list[dict]:
    return df[cols].head(n).to_dict(orient="records")


def follow_top10k(own: pd.DataFrame, n: int = 8) -> set[int]:
    """The players the top 10k bought most at the last deadline that I don't own."""
    bought = own[(~own["i_own"]) & (own["net_transfers"] > 0)]
    return set(bought.sort_values("net_transfers", ascending=False)["player_id"].head(n))


def build_payload(own: pd.DataFrame, suggestions: pd.DataFrame, follow: pd.DataFrame,
                  bootstrap: dict,
                  me: dict, sample_size: int, gameweek: int, next_gw: int | None,
                  horizon: list[int], rpp: float | None) -> dict:
    base = ["player_id", "web_name", "team", "position", "price_m", "ownership",
            "effective_ownership", "captain_share", "overall_ownership", "i_own",
            "my_multiplier", "net_transfers_share", "transfers_in", "transfers_out"]
    moved = own[own["sample_size"] > 0]
    bought = moved[moved["net_transfers"] > 0].sort_values("net_transfers", ascending=False)
    sold = moved[moved["net_transfers"] < 0].sort_values("net_transfers")

    # FPL-wide moves since the last deadline, from bootstrap-static
    teams = {t["id"]: t["short_name"] for t in bootstrap["teams"]}
    everyone = sorted(bootstrap["elements"],
                      key=lambda e: -(e.get("transfers_in_event", 0) - e.get("transfers_out_event", 0)))

    def ev(e):
        return {"player_id": e["id"], "web_name": e["web_name"], "team": teams.get(e["team"], ""),
                "net": e.get("transfers_in_event", 0) - e.get("transfers_out_event", 0)}

    threats = own[(~own["i_own"]) & (own["effective_ownership"] >= THREAT_EO)].copy()
    threats["haul_cost_ranks"] = [_ranks(HAUL_POINTS * e, rpp) for e in threats["effective_ownership"]]
    mine = own[own["i_own"]].copy()
    # positive = I gain on the top 10k when he scores; negative = I fall behind
    mine["exposure"] = (mine["my_multiplier"] - mine["effective_ownership"]).round(3)
    mine = mine.sort_values("exposure", ascending=False)

    best = suggestions.iloc[0].to_dict() if not suggestions.empty else None
    if best is None:
        verdict = "Roll the transfer: no swap in budget beats your squad by enough."
    elif best["net_gain"] < 1.0:
        verdict = (f"Probably roll: the best move ({best['out_name']} → {best['in_name']}) "
                   f"is only worth {best['net_gain']:+.1f} pts over {len(horizon)} gameweeks.")
    else:
        verdict = (f"{best['out_name']} → {best['in_name']}: {best['net_gain']:+.1f} expected pts "
                   f"over GW{horizon[0]}-{horizon[-1]}" +
                   (f", about {best['expected_rank_change']:+,} places" if best["expected_rank_change"] is not None else "") +
                   ("" if best["hit_cost"] == 0 else " after a -4 hit") + ".")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_gameweek": gameweek,
        "next_gameweek": next_gw,
        "horizon": horizon,
        "sample_size": sample_size,
        "top_n": TOP_N,
        "haul_points": HAUL_POINTS,
        "me": {**me, "ranks_per_point": rpp},
        "verdict": verdict,
        "suggestions": suggestions.to_dict(orient="records"),
        # the top 10k's most-bought players I don't own, each with my best sale
        "follow_top10k": follow.to_dict(orient="records"),
        "top10k_bought": _records(bought, base, 10),
        "top10k_sold": _records(sold, base, 10),
        "everyone_bought": [ev(e) for e in everyone[:8] if ev(e)["net"] > 0],
        "everyone_sold": [ev(e) for e in everyone[::-1][:8] if ev(e)["net"] < 0],
        "top10k_ownership": _records(own, base, 25),
        "threats": _records(threats, base + ["haul_cost_ranks"], 10),
        "my_exposure": _records(mine, base + ["exposure"], 15),
    }


# ---- orchestration ------------------------------------------------------------

def run(raw: dict, my_entry_id: int, powerbi_dir: Path, out_paths: list[Path],
        fetcher=fetch_top_sample) -> dict:
    """Fetch the top-10k sample, score transfers, write CSVs + transfers.json."""
    bootstrap = raw["bootstrap"]
    gameweek = int(raw["current_event"])
    next_gw = captain.next_gameweek(bootstrap)
    entry = raw["entry"]
    my_rank = entry.get("summary_overall_rank")

    sample = fetcher(gameweek, my_rank)
    own = build_ownership(sample, bootstrap, raw["entry_picks"])
    sample_size = int(own["sample_size"].max()) if not own.empty else 0
    rpp = ranks_per_point([r for page in sample.get("around_me", []) for r in page], my_rank)

    # expected points from the same star tables the captain picker uses
    fact_player_gw = powerbi.build_fact_player_gw(raw["event_live"])
    tables = {
        "fact_player_gw": fact_player_gw,
        "fact_team_fixture": powerbi.build_fact_team_fixture(raw["fixtures"]),
        "dim_player": powerbi.build_dim_player(bootstrap),
        "dim_team": powerbi.build_dim_team(bootstrap),
    }
    gws = sorted({e["id"] for e in bootstrap["events"]})
    horizon = [g for g in gws if next_gw is not None and next_gw <= g < next_gw + HORIZON]
    players = tables["dim_player"].copy()
    players["team"] = players["team_id"].map(tables["dim_team"].set_index("team_id")["short_name"])

    suggestions = pd.DataFrame(columns=SUGGESTION_COLUMNS)
    follow = pd.DataFrame(columns=SUGGESTION_COLUMNS)
    bank = raw["entry_picks"].get("entry_history", {}).get("bank", 0) / 10
    ft = free_transfers_estimate(raw["entry_history"], next_gw)
    if horizon:
        proj = project_points(tables, horizon, availability_from_bootstrap(bootstrap))
        sell = selling_prices(raw["entry_picks"], raw.get("entry_transfers") or [], bootstrap)
        suggestions = suggest(proj, own, players, raw["entry_picks"], sell, bank, ft,
                              rpp, next_gw, horizon)
        follow = suggest(proj, own, players, raw["entry_picks"], sell, bank, ft, rpp,
                         next_gw, horizon, only_in=follow_top10k(own),
                         min_gain=-math.inf, per_out=99)
        if not follow.empty:
            follow["rank"] = range(1, len(follow) + 1)

    powerbi_dir.mkdir(parents=True, exist_ok=True)
    if not own.empty:
        _upsert_gameweek(powerbi_dir / "fact_top10k_ownership.csv", own).to_csv(
            powerbi_dir / "fact_top10k_ownership.csv", index=False, encoding="utf-8")
    both = pd.concat([suggestions.assign(list="best_points"),
                      follow.assign(list="follow_top10k")], ignore_index=True)
    both = both[["list"] + SUGGESTION_COLUMNS]
    both.to_csv(powerbi_dir / "fact_transfer_suggestion.csv", index=False, encoding="utf-8")

    me = {"overall_rank": my_rank, "total_points": entry.get("summary_overall_points"),
          "bank_m": bank, "free_transfers": ft}
    payload = build_payload(own, suggestions, follow, bootstrap, me, sample_size, gameweek,
                            next_gw, horizon, rpp)
    text = json.dumps(payload, indent=2, default=str)
    for path in out_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return payload
