# Build the FPL Power BI report (beginner guide)

Goal: a 4-page Power BI report on your FPL season, fed automatically by the
GitHub pipeline. Plan for about 3 to 4 hours the first time.

German menu names are given in brackets. Power BI updates its wording now and
then, so if a label is slightly different, look for the same icon.

---

## Part 0 — Get real data into GitHub first (10 minutes)

The tables in `data/powerbi/` are created by the pipeline. Until the GitHub
Action has run once with the new code, those files contain demo numbers.

1. Copy the files from the zip into your local `fpl-analytics` folder
   (overwrite when Windows asks).
2. GitHub Desktop → you'll see the changed files → write a summary
   (`Add Power BI export`) → **Commit to master** → **Push origin**.
3. GitHub website → **Actions** → *Update FPL data & deploy dashboard* →
   **Run workflow**. Wait for the green tick.
4. On the **Code** tab open `data/powerbi/`. You should see 7 CSV files.
   Open `fact_my_gw.csv`: the numbers must match your real FPL points.

## Part 1 — Install and connect (20 minutes)

1. Install **Power BI Desktop** (free) from the Microsoft Store.
2. **Home → Get data → Blank query** (Start → Daten abrufen → Leere Abfrage).
3. **Home → Advanced Editor** (Erweiterter Editor). Delete the content and paste
   the `BaseUrl` block from `load_tables.pq` (just the one line with the URL).
   Done. Rename the query to `BaseUrl`.
4. Repeat steps 2 and 3 for the other 7 blocks in `load_tables.pq`. Name each
   query exactly as written (`dim_team`, `dim_player`, …).
5. If Power BI asks about credentials for `raw.githubusercontent.com`:
   choose **Anonymous** (Anonym) → **Connect**.
6. **Close & Apply** (Schließen und übernehmen).

## Part 2 — Data model (15 minutes)

1. Left bar → **Model view** (Modellansicht).
2. Check the lines between tables. Power BI may auto-create some. Compare with
   the relationship list at the top of `measures.dax` and fix any that differ
   (**Manage relationships** / Beziehungen verwalten).
3. Every relationship must be **Many to one**, direction **Single**, with the
   `dim_` table on the "one" side.
4. Arrange the tables like a star: the `dim_` tables on top, the `fact_`
   tables below. A screenshot of this view is a strong LinkedIn image.

## Part 3 — Measures (30 minutes)

1. **Home → Enter data**, leave it empty, name the table `_Measures`, **Load**.
2. Select `_Measures` → **New measure** (Neues Measure) and paste measures from
   `measures.dax` one at a time. Start with *Latest GW*, *GW Points*,
   *Total Points*, *Overall Rank*, *Rank Change Label*.
3. Add the three calculated columns at the bottom of the file:
   `Opponent` (on `fact_team_fixture`), `Ownership Band` and `Player Label`
   (on `dim_player`). Use **Table view → select table → New column**.
4. Check **Model Check (calc vs official)**: put it in a card. It should be 0
   or very close. If it isn't, your recomputed points differ from FPL's
   official points, and you've found something worth investigating (usually
   automatic substitutions or chips).

## Part 4 — Theme (2 minutes)

**View → Themes → Browse for themes** (Ansicht → Designs → Nach Designs
suchen) → select `fpl_theme.json`.

## Part 5 — The four pages

Use a 16:9 page. Give every page a title text box. Put a **Gameweek slicer**
(`dim_gameweek[gameweek]`, style "Between") on pages 1 and 2.

### Page 1 — Season overview
| Visual | Fields |
|---|---|
| Card | `Total Points` |
| Card | `Overall Rank`, subtitle `Rank Change Label` |
| Card | `Team Value` |
| Card | `Bench Points Wasted` |
| Card | `Hits Cost` |
| Line chart | X `dim_gameweek[gameweek]`, Y `Overall Rank`. Turn on **Y-axis → Range → Invert** (Y-Achse → Bereich → Umkehren), because rank 1 is best and should sit at the top |
| Column chart | X `dim_gameweek[gameweek]`, Y `GW Points`, add an **Average line** from the Analytics pane |

### Page 2 — Squad and captaincy
| Visual | Fields |
|---|---|
| Matrix | Rows `dim_player[web_name]`, Columns `dim_gameweek[gameweek]`, Values `Points Counted`. Add a colour scale (Conditional formatting → Background colour) |
| Clustered columns | X gameweek, Y `Captain Raw Points` and `Best Captain Raw Points` |
| Card | `Captain Regret` |
| Card | `Captain Hit Rate` (format as %) |
| Column chart | X gameweek, Y `Bench Points Wasted` |

This is the page that tells your story: *which gameweeks did the armband cost me?*

### Page 3 — Player value explorer
| Visual | Fields |
|---|---|
| Scatter | X `dim_player[price_m]`, Y `Points per 90`, Size `Ownership %`, Details `Player Label`, Legend `dim_player[position]` |
| Table | `web_name`, `team`, `price_m`, `total_points`, `Points per Million`, `Form L3`, `Ownership Band` (sort by `Points per Million`) |
| Slicers | `position`, `dim_team[team_name]`, `Ownership Band` |

Tip: add a **Minutes** filter (≥ 180) on the page, or players with one 90-minute
cameo will top every ranking.

### Page 4 — Fixtures
| Visual | Fields |
|---|---|
| Matrix (ticker) | Rows `dim_team[short_name]`, Columns `dim_gameweek[gameweek]`, Values `Fixture Label`. Filter gameweeks to > latest finished. Conditional formatting background rule based on `FDR`: 2 green, 3 neutral, 4–5 red |
| Bar chart | Axis `dim_team[short_name]`, Values `Avg FDR Next 5` (sorted ascending) |

## Part 6 — Publish and show it

- **File → Save as** `FPL_SRI.pbix`. Add the file to your GitHub repo in a
  `powerbi/` folder (it's small, so that's fine).
- Export each page as an image: **File → Export → Export to PDF**, or take
  screenshots at 100 percent zoom.
- Publishing to the web needs a work or school account, so for LinkedIn use
  screenshots, a short screen recording, and the link to the repo.

## Refreshing

Each Tuesday the Action updates the CSVs on GitHub. In Power BI Desktop click
**Refresh** (Aktualisieren) to load the new gameweek.

## Common problems

| Problem | Fix |
|---|---|
| Numbers show as dates or wrong decimals | You skipped the `"en-US"` in the type step of a query. Re-paste that block |
| `Web.Contents` credential error | Data source settings → **Anonymous** for raw.githubusercontent.com |
| Every card shows the same number for all players | A relationship is missing or the wrong way round (Part 2) |
| Rank line goes the wrong way | Invert the Y axis |
| *Model Check* isn't 0 | Compare one gameweek by hand against the FPL site. Chips (bench boost, triple captain) change how points count |
