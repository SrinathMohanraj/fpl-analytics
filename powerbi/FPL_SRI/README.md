# FPL_SRI Power BI project

A ready-made Power BI project (PBIP) with the whole report already built:
the 14 tables loaded from this repo's `data/powerbi/` CSVs (7 star-schema
tables plus the daily history tables `fact_value_daily` and `fact_price_daily`, the three rival tracker tables and the two captain picker tables),
the 19 relationships, all measures from `measures.dax` plus a few extras, the
`fpl_theme.json` theme, and seven pages:

1. **Season overview**: total points, overall rank, rank change, team value,
   bench points wasted and hits cards, the inverted overall rank line (log
   scale), and points per gameweek against the season average.
2. **Squad & captaincy**: captain regret, hit rate and raw captain points,
   captain vs best starter by gameweek, an armband table, and a player ×
   gameweek points matrix.
3. **Player value**: price vs points per 90 scatter (players with 270+
   minutes), a position slicer, and a points-per-£m table.
4. **Fixtures**: a fixture ticker for the next five gameweeks after the latest
   finished one, with difficulty, and the teams with the easiest run.
5. **Team value**: team value today, change today, change since tracking
   and your players' price moves cards, a day-by-day team value line, and
   your squad's current prices.
6. **Captain picker**: next gameweek's pick and its expected points, the
   whole squad ranked for the armband with the reason, and the backtest
   (picker's captain vs yours vs the best starter per gameweek).
7. **Rivals**: your league rank, points behind the leader, standings,
   league rank by gameweek per team, and who the league owns and captains.

The daily history tables (used on the Team value page) have these measures: **Team Value Today**, **Team Value Change Today**, **Team
Value Change Since Tracking**, **Price Change**, **My Squad Price Change** and
**Latest Price**.

### Rival tracker tables

Three more tables come from the mini-league rival tracker: `dim_league_entry`
(one row per manager per league, with `is_me`), `fact_league_gw` (points,
total, league rank and gap to me per gameweek) and `fact_league_picks` (who
owned and captained whom). They join on `league_entry_key`, and to
`dim_gameweek` and `dim_player`. Measures: **League Rank**, **My League
Rank**, **League Total Points**, **League GW Points**, **Gap To Me**,
**Points Behind Leader**, **League Owners**, **League Ownership %**,
**League Captained By** and **I Own (League)**. Quick visuals to try: a line
chart of `fact_league_gw[gameweek]` vs **League Rank** with
`dim_league_entry[entry_name]` as the legend (reverse the Y axis so 1st is at
the top), and a table of `dim_player[web_name]` with **League Ownership %**
and **I Own (League)**. Add a slicer on `dim_league_entry[league_name]` if
you track more than one league.

## Open it

1. Download the folder (or the zip) and keep the files together.
2. Double-click `FPL_SRI.pbip` (or Power BI Desktop → File → Open → choose it).
3. If Power BI asks how to connect to `raw.githubusercontent.com`, choose
   **Anonymous** → **Connect**.
4. Click **Refresh** so the tables load the latest data.
5. **File → Save as** → choose **Power BI file (.pbix)** → `FPL_SRI.pbix`.

If Desktop says it can't open the project format, turn on
**File → Options → Preview features → Power BI Project (.pbip) save option**
and **Store reports using enhanced metadata format (PBIR)**, restart Desktop
and open it again.

The data refreshes from GitHub every time you press Refresh, so the report
follows the weekly pipeline on its own.
