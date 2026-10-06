"""Generate a demo raw dataset shaped exactly like the real FPL API responses.

Why this exists: the live FPL API is only reachable from a machine with open
internet access (your laptop, or GitHub Actions) — not from this sandboxed
build environment. So this script fabricates realistic sample data with the
EXACT same schema the real `fetch.py` returns, which lets the rest of the
pipeline (clean -> metrics -> squad -> export) run and be verified end to end,
and gives the dashboard something to render before you've run the pipeline
for real.

Run it, then run the normal pipeline against the fake raw/ directory:

    python scripts/generate_demo_data.py
    python -c "from fpl_analytics import pipeline; pipeline.run(1702239)"

Swap in your real entry ID and delete data/raw/ before running the real
`python -m fpl_analytics.pipeline <entry_id>` once you have internet access —
it will overwrite these files with the live equivalents.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

random.seed(27)

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "raw"

TEAMS = [
    (1, "Arsenal", "ARS", 4), (2, "Aston Villa", "AVL", 3), (3, "Bournemouth", "BOU", 3),
    (4, "Brentford", "BRE", 3), (5, "Brighton", "BHA", 3), (6, "Chelsea", "CHE", 4),
    (7, "Crystal Palace", "CRY", 3), (8, "Everton", "EVE", 2), (9, "Fulham", "FUL", 2),
    (10, "Hull City", "HUL", 2), (11, "Ipswich Town", "IPS", 2), (12, "Leeds United", "LEE", 2),
    (13, "Liverpool", "LIV", 5), (14, "Man City", "MCI", 5), (15, "Man Utd", "MUN", 4),
    (16, "Newcastle", "NEW", 4), (17, "Nott'm Forest", "NFO", 3), (18, "Sunderland", "SUN", 2),
    (19, "Tottenham", "TOT", 4), (20, "Wolves", "WOL", 2),
]

# (first, last, team_id, position 1-4, price_tenths, total_points, form, minutes, ownership)
PLAYERS = [
    ("Yui", "Suzuki", 2, 1, 50, 62, 4.0, 405, 4.5),
    ("David", "Raya", 1, 1, 56, 71, 5.0, 450, 28.4),
    ("Robin", "Kinsky", 19, 1, 46, 44, 3.0, 360, 30.6),
    ("Martin", "Dubravka", 17, 1, 40, 38, 2.0, 405, 0.6),
    ("Oliwier", "Tzolakis", 13, 1, 40, 20, 1.0, 180, 0.2),
    ("Max", "Egan", 19, 2, 46, 55, 3.0, 450, 1.7),
    ("Nico", "O'Reilly", 14, 2, 50, 45, 2.0, 380, 5.1),
    ("Maxim", "De Cuyper", 5, 2, 45, 48, 3.0, 405, 2.2),
    ("Leif", "Ajer", 4, 2, 44, 40, 2.0, 400, 1.4),
    ("Riccardo", "Calafiori", 1, 2, 60, 58, 2.0, 420, 18.9),
    ("Ross", "Konsa", 2, 2, 44, 46, 2.0, 405, 4.6),
    ("Rico", "Hall", 15, 2, 45, 68, 4.0, 410, 6.9),
    ("Trevoh", "Chalobah", 6, 2, 51, 60, 4.0, 395, 7.8),
    ("Marcos", "Senesi", 3, 2, 46, 54, 3.0, 420, 9.4),
    ("Dean", "Egan-Riley", 7, 2, 50, 57, 3.0, 400, 8.1),
    ("Sepp", "van den Berg", 4, 2, 45, 42, 2.0, 390, 6.0),
    ("Bruno", "Fernandes", 15, 3, 90, 88, 6.0, 440, 24.1),
    ("Cole", "Palmer", 6, 3, 105, 76, 3.0, 400, 31.6),
    ("Bukayo", "Saka", 1, 3, 101, 82, 5.0, 420, 32.0),
    ("Antoine", "Semenyo", 3, 3, 76, 79, 6.0, 430, 18.3),
    ("Morgan", "Gibbs-White", 17, 3, 75, 70, 5.0, 410, 14.2),
    ("Jack", "Grealish", 8, 3, 67, 61, 4.0, 395, 10.7),
    ("Florian", "Wirtz", 13, 3, 80, 54, 3.0, 380, 22.4),
    ("Maghnes", "Akliouche", 2, 3, 65, 47, 3.0, 360, 5.6),
    ("Rayan", "Cherki", 14, 3, 65, 60, 4.0, 340, 8.8),
    ("Michael", "Groß", 5, 3, 56, 71, 6.0, 410, 26.9),
    ("Kiernan", "Dewsbury-Hall", 8, 3, 56, 58, 3.0, 420, 10.2),
    ("Jarrod", "Bowen", 7, 3, 78, 59, 4.0, 400, 12.0),
    ("Erling", "Haaland", 14, 4, 155, 101, 6.0, 430, 73.2),
    ("Alexander", "Isak", 13, 4, 104, 73, 4.0, 390, 24.6),
    ("Joao", "Pedro", 6, 4, 77, 66, 2.0, 400, 57.8),
    ("Ollie", "Watkins", 2, 4, 90, 55, 2.0, 370, 11.5),
    ("Igor", "Thiago", 4, 4, 80, 48, 2.0, 360, 9.2),
    ("Jean-Philippe", "Mateta", 7, 4, 75, 63, 4.0, 410, 13.8),
    ("Callum", "Thomas", 20, 4, 45, 51, 3.0, 380, 1.7),
    ("Josh", "King", 9, 3, 45, 33, 3.0, 310, 2.0),
    ("Marcus", "Barry", 14, 4, 50, 46, 4.0, 220, 22.2),
]

STATUS_POOL = ["a"] * 30 + ["d", "i"]  # mostly available, a few doubtful/injured


def build_bootstrap() -> dict:
    teams = [
        {"id": tid, "name": name, "short_name": short, "strength": strength,
         "strength_overall_home": strength + 1, "strength_overall_away": strength}
        for tid, name, short, strength in TEAMS
    ]
    elements = []
    for i, (first, last, team, pos, cost, pts, form, mins, own) in enumerate(PLAYERS, start=1):
        status = "a" if pts > 25 else random.choice(STATUS_POOL)
        elements.append({
            "id": i,
            "first_name": first,
            "second_name": last,
            "web_name": last,
            "team": team,
            "element_type": pos,
            "now_cost": cost,
            "total_points": pts,
            "form": str(form),
            "points_per_game": str(round(pts / 5, 1)),
            "minutes": mins,
            "goals_scored": random.randint(0, 9) if pos in (3, 4) else random.randint(0, 2),
            "assists": random.randint(0, 6),
            "clean_sheets": random.randint(0, 3) if pos in (1, 2) else 0,
            "bonus": random.randint(0, 10),
            "selected_by_percent": str(own),
            "ict_index": str(round(pts * random.uniform(1.1, 1.6), 1)),
            "status": status,
            "chance_of_playing_next_round": 75 if status == "d" else (0 if status == "i" else None),
        })

    events = []
    for gw in range(1, 39):
        events.append({
            "id": gw,
            "name": f"Gameweek {gw}",
            "is_current": gw == 5,
            "finished": gw < 5,
            "deadline_time": f"2026-{8 + (gw // 4):02d}-{(gw % 28) + 1:02d}T11:00:00Z",
        })

    return {"elements": elements, "teams": teams, "events": events}


def build_fixtures(bootstrap: dict) -> list:
    team_ids = [t["id"] for t in bootstrap["teams"]]
    fixtures = []
    fid = 1
    for gw in range(1, 9):
        shuffled = team_ids[:]
        random.shuffle(shuffled)
        for i in range(0, len(shuffled), 2):
            if i + 1 >= len(shuffled):
                continue
            fixtures.append({
                "id": fid,
                "event": gw,
                "team_h": shuffled[i],
                "team_a": shuffled[i + 1],
                "team_h_difficulty": random.randint(2, 5),
                "team_a_difficulty": random.randint(2, 5),
                "finished": gw < 5,
                "team_h_score": random.randint(0, 3) if gw < 5 else None,
                "team_a_score": random.randint(0, 3) if gw < 5 else None,
                "kickoff_time": f"2026-{8 + (gw // 4):02d}-{(gw % 28) + 1:02d}T14:00:00Z",
            })
            fid += 1
    return fixtures


def build_entry(entry_id: int) -> dict:
    return {
        "id": entry_id,
        "player_first_name": "Srinath",
        "player_last_name": "M",
        "name": "FPL_SRI",
        "summary_overall_points": 290,
        "summary_overall_rank": 45161,
    }


def build_entry_history(entry_id: int) -> dict:
    # Consistent with the known data point: GW5 = 59 pts, overall rank 45,161,
    # and a +52,027 rank climb that week (so GW4 overall rank = 97,188).
    rows = [
        {"event": 1, "points": 85, "total_points": 85, "rank": 1_800_000,
         "overall_rank": 1_800_000, "bank": 2, "value": 1000,
         "event_transfers": 0, "event_transfers_cost": 0, "points_on_bench": 11},
        {"event": 2, "points": 61, "total_points": 146, "rank": 2_100_000,
         "overall_rank": 980_000, "bank": 2, "value": 1002,
         "event_transfers": 1, "event_transfers_cost": 0, "points_on_bench": 6},
        {"event": 3, "points": 58, "total_points": 204, "rank": 2_300_000,
         "overall_rank": 540_000, "bank": 3, "value": 1004,
         "event_transfers": 1, "event_transfers_cost": 0, "points_on_bench": 9},
        {"event": 4, "points": 47, "total_points": 251, "rank": 3_000_000,
         "overall_rank": 97_188, "bank": 3, "value": 1006,
         "event_transfers": 1, "event_transfers_cost": 0, "points_on_bench": 4},
        {"event": 5, "points": 59, "total_points": 310, "rank": 900_000,
         "overall_rank": 45_161, "bank": 3, "value": 1008,
         "event_transfers": 2, "event_transfers_cost": 4, "points_on_bench": 7},
    ]
    return {"current": rows, "past": []}


def build_entry_picks(entry_id: int) -> dict:
    # Matches the GW5 screenshot squad: Kinsky; Konsa, Calafiori (C), Hall;
    # Palmer, Cherki, Dewsbury-Hall, Saka, Groß; Barry, Haaland.
    # Bench: Dubravka, Joao Pedro, Thomas, [one more sub].
    name_to_id = {f"{p[0]} {p[1]}": i for i, p in enumerate(PLAYERS, start=1)}

    def pick(name: str, slot: int, mult: int, captain=False, vice=False):
        return {
            "element": name_to_id[name],
            "position": slot,
            "multiplier": mult,
            "is_captain": captain,
            "is_vice_captain": vice,
        }

    picks = [
        pick("Robin Kinsky", 1, 1),
        pick("Ross Konsa", 2, 1),
        pick("Riccardo Calafiori", 3, 2, captain=True),
        pick("Rico Hall", 4, 1),
        pick("Cole Palmer", 5, 1),
        pick("Rayan Cherki", 6, 1),
        pick("Kiernan Dewsbury-Hall", 7, 1, vice=True),
        pick("Bukayo Saka", 8, 1),
        pick("Michael Groß", 9, 1),
        pick("Marcus Barry", 10, 1),
        pick("Erling Haaland", 11, 1),
        pick("Martin Dubravka", 12, 0),
        pick("Joao Pedro", 13, 0),
        pick("Callum Thomas", 14, 0),
        pick("Josh King", 15, 0),
    ]
    return {"picks": picks, "entry_history": {"event": 5, "points": 59}}


def build_entry_transfers(entry_id: int) -> list:
    return [
        {"element_in": 1, "element_out": 2, "event": 4, "time": "2026-09-13T10:00:00Z"},
        {"element_in": 3, "element_out": 4, "event": 5, "time": "2026-09-20T10:00:00Z"},
    ]


def main(entry_id: int = 1702239) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    bootstrap = build_bootstrap()
    payload = {
        "bootstrap": bootstrap,
        "fixtures": build_fixtures(bootstrap),
        "entry": build_entry(entry_id),
        "entry_history": build_entry_history(entry_id),
        "entry_picks": build_entry_picks(entry_id),
        "entry_transfers": build_entry_transfers(entry_id),
    }
    for name, data in payload.items():
        (RAW_DIR / f"{name}.json").write_text(json.dumps(data, indent=2))
    print(f"Demo raw data written to {RAW_DIR} (entry_id={entry_id}, current_event=5)")


if __name__ == "__main__":
    main()
