"""Captain picker: rank my squad for the next gameweek and backtest the idea.

How a player is scored for gameweek t (only data from gameweeks before t is
used, so the backtest never peeks at the result):

    expected points = (0.2 x recent form          points per GW, last 4 GWs
                       + 0.5 x season points/game  GWs with minutes
                       + 0.3 x attacking threat)   xG and xA turned into points
                      x minutes security           share of 90 mins, last 4 GWs
                      x fixture factor             per fixture, summed for doubles
                      x availability               injury flag (live picks only)

The fixture factor uses FPL's own difficulty rating (FDR, 1 easy to 5 hard):
each step easier than an average fixture (3) adds 15%, and home adds 5%.
The weights were chosen by testing a grid of them on every Premier League
player's gameweeks 3-10 of 2026/27 (which order best matched the real points),
not on my own picks, so the backtest is not tuned to my results. Season
points/game and the fixture mattered more than the last 4 weeks of form.

Everything works on the Power BI star tables from powerbi.py, so the same code
runs in the weekly pipeline and offline against data/powerbi/*.csv.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import powerbi

FORM_WINDOW = 4          # gameweeks that count as "recent"
W_FORM, W_SEASON, W_THREAT = 0.2, 0.5, 0.3
FDR_STEP = 0.15          # +15% per FDR step easier than 3
HOME_BONUS = 0.05
# rough FPL points for a goal / assist by position, to turn xG and xA into points
GOAL_PTS = {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}
ASSIST_PTS = 3
# chance of playing when FPL flags a player (status codes from bootstrap-static)
STATUS_AVAILABILITY = {"a": 1.0, "d": 0.5, "i": 0.0, "s": 0.0, "u": 0.0, "n": 0.0}


def _fixtures_for(fixtures: pd.DataFrame, gameweek: int) -> pd.DataFrame:
    return fixtures[fixtures["gameweek"] == gameweek]


def score_players(player_gw: pd.DataFrame, fixtures: pd.DataFrame, players: pd.DataFrame,
                  teams: pd.DataFrame, gameweek: int, player_ids=None,
                  availability: dict | None = None) -> pd.DataFrame:
    """Expected points for each player in `gameweek`, using only earlier gameweeks.

    `availability` maps player_id -> 0..1 chance of playing. Leave it out for the
    backtest (FPL's injury flags are only known for the upcoming gameweek).
    """
    past = player_gw[player_gw["gameweek"] < gameweek]
    if player_ids is not None:
        past = past[past["player_id"].isin(player_ids)]
    # ignore blank gameweeks (team had no match), so they don't look like
    # lost minutes or bad form
    team_of = players.set_index("player_id")["team_id"]
    played_fx = set(zip(fixtures["gameweek"], fixtures["team_id"]))
    had_match = [(gw, team_of.get(pid)) in played_fx
                 for gw, pid in zip(past["gameweek"], past["player_id"])]
    past = past[had_match]
    recent = past[past["gameweek"] >= gameweek - FORM_WINDOW]

    rec = recent.groupby("player_id").agg(
        form=("total_points", "mean"),
        minutes_avg=("minutes", "mean"),
        xg=("expected_goals", "mean"),
        xa=("expected_assists", "mean"),
    )
    played = past[past["minutes"] > 0]
    ppg = played.groupby("player_id")["total_points"].mean().rename("season_ppg")
    df = rec.join(ppg, how="left").fillna({"season_ppg": 0.0}).reset_index()
    if player_ids is not None:
        df = pd.DataFrame({"player_id": list(player_ids)}).merge(df, on="player_id", how="left")
    df = df.fillna(0.0)

    df = df.merge(players[["player_id", "web_name", "team_id", "position"]], on="player_id", how="left")
    df["threat"] = df["xg"] * df["position"].map(GOAL_PTS).fillna(4) + df["xa"] * ASSIST_PTS
    df["minutes_security"] = (df["minutes_avg"] / 90).clip(upper=1.0)

    # fixture factor, summed over fixtures (0 in a blank, ~2x in a double)
    fx = _fixtures_for(fixtures, gameweek).copy()
    fx["factor"] = (1 + FDR_STEP * (3 - fx["difficulty"].fillna(3))
                    + HOME_BONUS * fx["is_home"].astype(bool))
    short = teams.set_index("team_id")["short_name"]
    fx["label"] = (fx["opponent_id"].map(short).fillna("?")
                   + fx["is_home"].map({True: " (H)", False: " (A)"})
                   + " FDR " + fx["difficulty"].fillna(3).astype(int).astype(str))
    per_team = fx.groupby("team_id").agg(fixture_factor=("factor", "sum"),
                                         fixtures=("label", " + ".join),
                                         fdr=("difficulty", "mean"),
                                         n_fixtures=("factor", "size"))
    df = df.merge(per_team, left_on="team_id", right_index=True, how="left")
    df = df.fillna({"fixture_factor": 0.0, "fixtures": "No fixture", "n_fixtures": 0})

    df["availability"] = 1.0 if availability is None else \
        df["player_id"].map(availability).fillna(1.0)
    base = W_FORM * df["form"] + W_SEASON * df["season_ppg"] + W_THREAT * df["threat"]
    df["expected_points"] = (base * df["minutes_security"] * df["fixture_factor"]
                             * df["availability"]).round(2)
    df["gameweek"] = gameweek
    return df


def _reason(r) -> str:
    """One short line saying why a player ranks where they do."""
    if r["n_fixtures"] == 0:
        return "No fixture this gameweek"
    if r["availability"] == 0:
        return "Flagged injured or suspended"
    parts = []
    if r["n_fixtures"] > 1:
        parts.append("Double gameweek")
    parts.append(f"{r['season_ppg']:.1f} pts/game this season, {r['form']:.1f} in last {FORM_WINDOW}")
    fdr = r["fdr"]
    ease = "easy" if fdr <= 2 else ("tough" if fdr >= 4 else "average")
    parts.append(f"{ease} fixture")
    if r["xg"] + r["xa"] >= 0.4:
        parts.append(f"xGI {r['xg'] + r['xa']:.2f}/GW")
    if r["minutes_security"] < 0.7:
        parts.append("minutes at risk")
    if 0 < r["availability"] < 1:
        parts.append("injury doubt")
    return "; ".join(parts)


def rank_squad(tables: dict, squad_ids, gameweek: int,
               availability: dict | None = None) -> pd.DataFrame:
    """Rank the given players for `gameweek`, best captain first, with reasons."""
    df = score_players(tables["fact_player_gw"], tables["fact_team_fixture"],
                       tables["dim_player"], tables["dim_team"], gameweek,
                       player_ids=list(squad_ids), availability=availability)
    df = df.sort_values("expected_points", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)
    df["reason"] = df.apply(_reason, axis=1)
    cols = ["gameweek", "rank", "player_id", "web_name", "position", "fixtures",
            "expected_points", "form", "season_ppg", "threat", "minutes_security",
            "fixture_factor", "availability", "reason"]
    return df[cols].round({"form": 2, "season_ppg": 2, "threat": 2,
                           "minutes_security": 2, "fixture_factor": 2})


def backtest(tables: dict, first_gw: int = 3) -> pd.DataFrame:
    """For each finished gameweek: what the picker would have chosen from my XI,
    versus the captain I actually chose and the best possible captain.

    Points are the captain's own score (the armband doubles it, so this is also
    the extra points the armband earned). Uses the XI as picked (slots 1-11).
    Starts at GW3, because after GW1 alone there is too little history to score.
    """
    squad = tables["fact_my_squad"]
    names = tables["dim_player"].set_index("player_id")["web_name"]
    rows = []
    for gw in sorted(squad["gameweek"].unique()):
        if gw < first_gw:
            continue
        xi = squad[(squad["gameweek"] == gw) & (squad["squad_slot"] <= 11)]
        pts = xi.set_index("player_id")["player_points"]
        ranked = rank_squad(tables, xi["player_id"], gw)
        pick = ranked.iloc[0]
        mine = xi[xi["is_captain"]].iloc[0]
        best_pid = pts.idxmax()
        rows.append({
            "gameweek": int(gw),
            "picker_captain": pick["web_name"],
            "picker_expected": float(pick["expected_points"]),
            "picker_points": float(pts[pick["player_id"]]),
            "my_captain": names.get(mine["player_id"], str(mine["player_id"])),
            "my_points": float(mine["player_points"]),
            "best_captain": names.get(best_pid, str(best_pid)),
            "best_points": float(pts.max()),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["picker_vs_me"] = df["picker_points"] - df["my_points"]
    df["my_regret"] = df["best_points"] - df["my_points"]
    df["picker_regret"] = df["best_points"] - df["picker_points"]
    return df


def backtest_summary(bt: pd.DataFrame) -> dict:
    if bt.empty:
        return {}
    return {
        "gameweeks": int(len(bt)),
        "from_gw": int(bt["gameweek"].min()),
        "to_gw": int(bt["gameweek"].max()),
        "picker_points": float(bt["picker_points"].sum()),
        "my_points": float(bt["my_points"].sum()),
        "best_points": float(bt["best_points"].sum()),
        "picker_gain": float(bt["picker_vs_me"].sum()),
        "picker_better_weeks": int((bt["picker_vs_me"] > 0).sum()),
        "picker_worse_weeks": int((bt["picker_vs_me"] < 0).sum()),
        "picker_hits": int((bt["picker_regret"] == 0).sum()),
        "my_hits": int((bt["my_regret"] == 0).sum()),
    }


def availability_from_players(players: pd.DataFrame) -> dict:
    """player_id -> chance of playing next GW, from bootstrap-static flags."""
    chance = pd.to_numeric(players.get("chance_of_playing_next_round"), errors="coerce") / 100
    status = players["status"].map(STATUS_AVAILABILITY).fillna(1.0)
    return dict(zip(players["id"], chance.fillna(status)))


def build(tables: dict, next_gw: int | None, squad_ids, availability: dict | None = None) -> dict:
    """Everything the dashboard and Power BI need, in one call."""
    bt = backtest(tables)
    ranking = (rank_squad(tables, squad_ids, next_gw, availability)
               if next_gw is not None else pd.DataFrame())
    return {"next_gameweek": next_gw, "ranking": ranking, "backtest": bt,
            "summary": backtest_summary(bt)}


def next_gameweek(bootstrap: dict) -> int | None:
    """The gameweek whose deadline is next (None once the season is over)."""
    nxt = next((e["id"] for e in bootstrap["events"] if e.get("is_next")), None)
    if nxt is None:
        unfinished = [e["id"] for e in bootstrap["events"] if not e.get("finished")]
        nxt = min(unfinished) if unfinished else None
    return nxt


def pipeline_step(raw: dict, players: pd.DataFrame, out_dir: Path) -> dict:
    """Run the picker inside pipeline.py: write two Power BI CSVs, return the
    dashboard.json section. Needs the per-gameweek data (event_live, picks_by_gw).

    The squad is the latest one FPL shows (my picks for the current gameweek),
    so transfers made before the next deadline only show up after it.
    """
    if "event_live" not in raw or "picks_by_gw" not in raw:
        return {}
    fact_player_gw = powerbi.build_fact_player_gw(raw["event_live"])
    tables = {
        "fact_player_gw": fact_player_gw,
        "fact_team_fixture": powerbi.build_fact_team_fixture(raw["fixtures"]),
        "dim_player": powerbi.build_dim_player(raw["bootstrap"]),
        "dim_team": powerbi.build_dim_team(raw["bootstrap"]),
        "fact_my_squad": powerbi.build_fact_my_squad(raw["picks_by_gw"], fact_player_gw),
    }
    picks = raw["entry_picks"]["picks"]
    bench = {p["element"] for p in picks if p["position"] > 11}
    result = build(tables, next_gameweek(raw["bootstrap"]),
                   [p["element"] for p in picks], availability_from_players(players))

    ranking, bt = result["ranking"], result["backtest"]
    if not ranking.empty:
        ranking.insert(5, "on_bench", ranking["player_id"].isin(bench))
    out_dir.mkdir(parents=True, exist_ok=True)
    ranking.to_csv(out_dir / "fact_captain_pick.csv", index=False, encoding="utf-8")
    bt.to_csv(out_dir / "fact_captain_backtest.csv", index=False, encoding="utf-8")
    return {
        "next_gameweek": result["next_gameweek"],
        "ranking": ranking.to_dict(orient="records"),
        "backtest": bt.to_dict(orient="records"),
        "summary": result["summary"],
    }


def run_offline(powerbi_dir: Path, dashboard_json: list[Path] | None = None) -> dict:
    """Run the picker from the saved data/powerbi CSVs, no internet needed.

    Uses the latest squad in fact_my_squad and FPL's status flags in dim_player.
    Rewrites the two captain CSVs and, if given, the captain section of the
    dashboard.json files.
    """
    import json

    names = ["fact_player_gw", "fact_team_fixture", "dim_player", "dim_team",
             "fact_my_squad", "dim_gameweek"]
    tables = {n: pd.read_csv(powerbi_dir / f"{n}.csv") for n in names}
    squad = tables["fact_my_squad"]
    latest = squad[squad["gameweek"] == squad["gameweek"].max()]
    gws = tables["dim_gameweek"]
    unfinished = gws[~gws["finished"].astype(bool)]["gameweek"]
    next_gw = int(unfinished.min()) if len(unfinished) else None

    players = tables["dim_player"]
    availability = dict(zip(players["player_id"],
                            players["status"].map(STATUS_AVAILABILITY).fillna(1.0)))
    result = build(tables, next_gw, latest["player_id"], availability)
    ranking, bt = result["ranking"], result["backtest"]
    if not ranking.empty:
        bench = set(latest.loc[latest["squad_slot"] > 11, "player_id"])
        ranking.insert(5, "on_bench", ranking["player_id"].isin(bench))
    ranking.to_csv(powerbi_dir / "fact_captain_pick.csv", index=False, encoding="utf-8")
    bt.to_csv(powerbi_dir / "fact_captain_backtest.csv", index=False, encoding="utf-8")

    section = {"next_gameweek": next_gw, "ranking": ranking.to_dict(orient="records"),
               "backtest": bt.to_dict(orient="records"), "summary": result["summary"]}
    for path in dashboard_json or []:
        payload = json.loads(path.read_text())
        payload["captain_picker"] = section
        path.write_text(json.dumps(payload, indent=2, default=str))
    return section


if __name__ == "__main__":
    # python -m fpl_analytics.captain   (refresh the picker from saved CSVs)
    root = Path(__file__).resolve().parents[2]
    out = run_offline(root / "data" / "powerbi",
                      [root / "data" / "processed" / "dashboard.json",
                       root / "dashboard" / "data" / "dashboard.json"])
    top = out["ranking"][0] if out["ranking"] else None
    if top:
        print(f"GW{out['next_gameweek']} captain: {top['web_name']} ({top['expected_points']} expected pts)")
    print("Backtest:", out["summary"])
