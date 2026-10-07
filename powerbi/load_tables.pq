// =====================================================================
// FPL Analytics — Power Query (M) code for Power BI
// =====================================================================
// HOW TO USE
//  1. Power BI Desktop -> Home -> Get data -> Blank query
//  2. Home -> Advanced Editor, delete everything, paste ONE block below
//  3. Rename the query (right-hand panel) to exactly the name in the
//     "// QUERY NAME:" line, then Done
//  4. Repeat for every block (7 tables). Start with BaseUrl.
//
// Why "en-US" in every type step: your Windows is German, so Power BI would
// read "5.5" as a date or fail. Forcing en-US makes decimals always parse.
// =====================================================================


// ---------------------------------------------------------------------
// QUERY NAME: BaseUrl      (a plain text query, not a table)
// ---------------------------------------------------------------------
"https://raw.githubusercontent.com/SrinathMohanraj/fpl-analytics/master/data/powerbi/"


// ---------------------------------------------------------------------
// QUERY NAME: dim_team
// ---------------------------------------------------------------------
let
    Source = Csv.Document(Web.Contents(BaseUrl & "dim_team.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"team_id", Int64.Type}, {"team_name", type text},
        {"short_name", type text}, {"strength", Int64.Type}}, "en-US")
in
    Typed


// ---------------------------------------------------------------------
// QUERY NAME: dim_player
// ---------------------------------------------------------------------
let
    Source = Csv.Document(Web.Contents(BaseUrl & "dim_player.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"player_id", Int64.Type}, {"web_name", type text}, {"full_name", type text},
        {"team_id", Int64.Type}, {"position", type text}, {"price_m", type number},
        {"selected_by_percent", type number}, {"form", type number},
        {"total_points", Int64.Type}, {"status", type text}}, "en-US")
in
    Typed


// ---------------------------------------------------------------------
// QUERY NAME: dim_gameweek
// ---------------------------------------------------------------------
let
    Source = Csv.Document(Web.Contents(BaseUrl & "dim_gameweek.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"gameweek", Int64.Type}, {"name", type text}, {"deadline_date", type date},
        {"finished", type logical}, {"is_current", type logical}}, "en-US")
in
    Typed


// ---------------------------------------------------------------------
// QUERY NAME: fact_player_gw
// ---------------------------------------------------------------------
let
    Source = Csv.Document(Web.Contents(BaseUrl & "fact_player_gw.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"player_id", Int64.Type}, {"gameweek", Int64.Type}, {"minutes", Int64.Type},
        {"total_points", Int64.Type}, {"goals_scored", Int64.Type}, {"assists", Int64.Type},
        {"clean_sheets", Int64.Type}, {"goals_conceded", Int64.Type}, {"saves", Int64.Type},
        {"bonus", Int64.Type}, {"bps", Int64.Type}, {"yellow_cards", Int64.Type},
        {"red_cards", Int64.Type}, {"expected_goals", type number},
        {"expected_assists", type number}, {"expected_goal_involvements", type number},
        {"defensive_contribution", Int64.Type}}, "en-US")
in
    Typed


// ---------------------------------------------------------------------
// QUERY NAME: fact_my_squad
// ---------------------------------------------------------------------
let
    Source = Csv.Document(Web.Contents(BaseUrl & "fact_my_squad.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"gameweek", Int64.Type}, {"player_id", Int64.Type}, {"squad_slot", Int64.Type},
        {"is_captain", type logical}, {"is_vice_captain", type logical},
        {"started", type logical}, {"multiplier", Int64.Type},
        {"player_points", type number}, {"points_counted", type number},
        {"points_on_bench", type number}}, "en-US")
in
    Typed


// ---------------------------------------------------------------------
// QUERY NAME: fact_my_gw
// ---------------------------------------------------------------------
let
    Source = Csv.Document(Web.Contents(BaseUrl & "fact_my_gw.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"gameweek", Int64.Type}, {"points", Int64.Type}, {"total_points", Int64.Type},
        {"gw_rank", Int64.Type}, {"overall_rank", Int64.Type}, {"bank", type number},
        {"team_value", type number}, {"transfers_made", Int64.Type},
        {"transfer_cost", Int64.Type}, {"bench_points", Int64.Type},
        {"calc_points", type number}, {"points_diff_vs_official", type number}}, "en-US")
in
    Typed


// ---------------------------------------------------------------------
// QUERY NAME: fact_team_fixture
// ---------------------------------------------------------------------
let
    Source = Csv.Document(Web.Contents(BaseUrl & "fact_team_fixture.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Typed = Table.TransformColumnTypes(Promoted, {
        {"gameweek", Int64.Type}, {"kickoff_time", type datetimezone},
        {"finished", type logical}, {"team_id", Int64.Type}, {"opponent_id", Int64.Type},
        {"is_home", type logical}, {"difficulty", Int64.Type},
        {"goals_for", Int64.Type}, {"goals_against", Int64.Type}}, "en-US")
in
    Typed
