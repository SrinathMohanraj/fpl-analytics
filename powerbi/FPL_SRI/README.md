# FPL_SRI Power BI project

A ready-made Power BI project (PBIP) with the whole report already built:
the 7 star-schema tables loaded from this repo's `data/powerbi/` CSVs, the 8
relationships, all measures from `measures.dax` plus a few extras, the
`fpl_theme.json` theme, and four pages:

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
