"""Table and column definitions of the model and the Excel writer.

`build_workbook` writes a dict of DataFrames to an .xlsx file with one Excel Table per sheet.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

STAGES = ["League", "Group", "League phase", "Cup round", "Playoff",
          "R32", "R16", "QF", "SF", "Final", "Other", "Winner"]

# name -> (description, source, [(column, type, description, dropdown options)])
TABLES: dict[str, tuple[str, str, list[tuple[str, str, str, list[str] | None]]]] = {
    "DimPlayer": ("Players. One row = one player.", "Wikipedia, SofaScore, data/manual/players.csv", [
        ("PlayerID", "Text", "Key: slug of the name, e.g. harry-kane", None),
        ("PlayerName", "Text", "Player name", None),
        ("Nationality", "Text", "National team", None),
        ("Position", "Text", "Position from the source, e.g. FW or FW-MF", None),
        ("PositionGroup", "Text", "Position group", ["FW", "MF", "DF", "GK"]),
        ("BirthDate", "Date", "Date of birth", None),
        ("SofascoreID", "Text", "Player ID on SofaScore", None),
    ]),
    "DimTeam": ("Clubs and national teams. One row = one team.", "SofaScore matches and league tables", [
        ("TeamID", "Text", "Key: t- + slug of the name", None),
        ("TeamName", "Text", "Name as in the source", None),
        ("TeamType", "Text", "Club or national team", ["Club", "National"]),
        ("League", "Text", "League (clubs of a loaded league)", None),
    ]),
    "DimCompetition": ("Competitions. One row = one competition.", "etl/config.yaml", [
        ("CompetitionID", "Text", "Key: slug of the name", None),
        ("CompetitionName", "Text", "Name (used in DAX)", None),
        ("CompetitionType", "Text", "Competition type",
         ["League", "Domestic Cup", "Super Cup", "Continental", "International", "Qualifier", "Other"]),
        ("IsBigStage", "Boolean", "TRUE for the Champions League, World Cup, Euro, Copa América, AFCON", ["TRUE", "FALSE"]),
    ]),
    "DimSeason": ("Ceremonies. One row = one award year.", "etl/config.yaml + Wikipedia", [
        ("SeasonID", "Text", "Key, format YYYY-YY (the season that ended in the award year)", None),
        ("BallonDorYear", "Whole number", "Award year", None),
        ("StartDate", "Date", "Start of the evaluation period", None),
        ("EndDate", "Date", "End of the evaluation period", None),
        ("VotersCount", "Whole number", "Number of voters (from config, or estimated from total points)", None),
        ("MaxPointsPerBallot", "Whole number", "Points for 1st place on one ballot", None),
    ]),
    "FactPlayerMatch": ("Nominees' matches in match_level_years. One row = player × match.", "SofaScore", [
        ("MatchID", "Text", "Key: date + teams", None),
        ("Date", "Date", "Match date", None),
        ("SeasonID", "Text", "→ DimSeason", None),
        ("PlayerID", "Text", "→ DimPlayer", None),
        ("TeamID", "Text", "→ DimTeam (player's team)", None),
        ("OpponentTeamID", "Text", "→ DimTeam (opponent, inactive relationship)", None),
        ("CompetitionID", "Text", "→ DimCompetition", None),
        ("Stage", "Text", "Match stage", STAGES[:-1]),
        ("IsKnockout", "Boolean", "TRUE for knockout matches", ["TRUE", "FALSE"]),
        ("IsVsTop6", "Boolean", "Opponent in the top 6 of a big-5 league or in data/manual/top_opponents.csv", ["TRUE", "FALSE"]),
        ("Minutes", "Whole number", "Minutes played", None),
        ("Goals", "Whole number", "Goals (including penalties)", None),
        ("PenaltyGoals", "Whole number", "Penalty goals", None),
        ("Assists", "Whole number", "Assists", None),
        ("xG", "Decimal", "Expected goals", None),
        ("npxG", "Decimal", "Non-penalty xG", None),
        ("xA", "Decimal", "Expected assists (xAG)", None),
        ("Shots", "Whole number", "Shots", None),
        ("ShotsOnTarget", "Whole number", "Shots on target", None),
        ("DecisiveGoals", "Whole number", "Estimate: goals without which the result would have been worse", None),
        ("Rating", "Decimal", "SofaScore match rating or data/manual/ratings.csv (manual wins)", None),
        ("TeamGoals", "Whole number", "Goals of the player's team in the match", None),
        ("Result", "Text", "Result for the player's team", ["W", "D", "L"]),
        ("xGIncEst", "Decimal", "xG including an estimate: the source's xG, or shots × npxG per shot (+0.79 per penalty goal) where the source has none. For season totals only", None),
        ("npxGIncEst", "Decimal", "npxG including an estimate (as xGIncEst, without penalties). For season totals only", None),
        ("IsXgEstimated", "Boolean", "TRUE when xGIncEst and npxGIncEst are estimates (the source has no xG for the match)", ["TRUE", "FALSE"]),
    ]),
    "FactPlayerSeason": ("Nominees' season totals. One row = player × award year.", "FactPlayerMatch", [
        ("SeasonID", "Text", "→ DimSeason", None),
        ("PlayerID", "Text", "→ DimPlayer", None),
        ("TeamID", "Text", "→ DimTeam (club with the most minutes)", None),
        ("Matches", "Whole number", "Matches", None),
        ("Minutes", "Whole number", "Minutes", None),
        ("Goals", "Whole number", "Goals", None),
        ("PenaltyGoals", "Whole number", "Penalty goals", None),
        ("Assists", "Whole number", "Assists", None),
        ("xG", "Decimal", "xG", None),
        ("npxG", "Decimal", "npxG", None),
        ("xA", "Decimal", "xAG", None),
        ("BigStageKnockoutGA", "Whole number", "G+A in knockout matches of IsBigStage competitions", None),
        ("LeaguePosition", "Whole number", "Final league position of the main club", None),
        ("MinutesWithXg", "Whole number", "Minutes in matches with xG from the source (denominator of per-90 xG)", None),
        ("xGIncEst", "Decimal", "Season xG including the estimate for matches without xG", None),
        ("npxGIncEst", "Decimal", "Season npxG including the estimate for matches without xG", None),
    ]),
    "FactVoting": ("Voting results. One row = player × ceremony.", "Wikipedia", [
        ("SeasonID", "Text", "→ DimSeason", None),
        ("PlayerID", "Text", "→ DimPlayer", None),
        ("Rank", "Whole number", "Final rank", None),
        ("Points", "Whole number", "Points (empty for 2010–2015: FIFA published percentages)", None),
        ("VoteSharePct", "Decimal", "Vote share when published as a percentage (0–1)", None),
        ("FirstPlaceVotes", "Whole number", "First-place votes (data/manual/first_place_votes.csv)", None),
    ]),
    "FactPlayerCompetition": ("Result of the player's team in a competition. One row = player × competition × award year.", "SofaScore matches and league tables, data/manual/competition_overrides.csv", [
        ("SeasonID", "Text", "→ DimSeason", None),
        ("PlayerID", "Text", "→ DimPlayer", None),
        ("TeamID", "Text", "→ DimTeam", None),
        ("CompetitionID", "Text", "→ DimCompetition", None),
        ("StageReached", "Text", "Furthest stage reached", STAGES),
        ("StageOrder", "Whole number", "Stage number (leagues: teams − position + 1)", None),
        ("MaxStageOrder", "Whole number", "StageOrder of the winner", None),
        ("IsWinner", "Boolean", "Trophy won", ["TRUE", "FALSE"]),
        ("TrophyTier", "Text", "Major / Minor", ["Major", "Minor"]),
        ("TrophyWeight", "Decimal", "Trophy weight from config", None),
    ]),
    "IndexWeights": ("Weights of the composite index. They sum to 1.", "Author's assumption", [
        ("Component", "Text", "Index component", ["Output", "Trophies", "BigGames"]),
        ("Weight", "Decimal", "Weight", None),
    ]),
}

DEFAULT_WEIGHTS = pd.DataFrame({"Component": ["Output", "Trophies", "BigGames"],
                                "Weight": [0.40, 0.35, 0.25]})

# One illustrative row per table for the template workbook (etl.run --template).
EXAMPLE_ROWS: dict[str, dict] = {
    "DimPlayer": {"PlayerID": "harry-kane", "PlayerName": "Harry Kane", "Nationality": "England", "Position": "FW",
                  "PositionGroup": "FW", "BirthDate": dt.date(1993, 7, 28), "SofascoreID": "108579"},
    "DimTeam": {"TeamID": "t-bayern-munchen", "TeamName": "Bayern München", "TeamType": "Club", "League": "Bundesliga"},
    "DimCompetition": {"CompetitionID": "uefa-champions-league", "CompetitionName": "UEFA Champions League",
                       "CompetitionType": "Continental", "IsBigStage": True},
    "DimSeason": {"SeasonID": "2025-26", "BallonDorYear": 2026, "StartDate": dt.date(2025, 8, 1),
                  "EndDate": dt.date(2026, 7, 31), "VotersCount": 100, "MaxPointsPerBallot": 15},
    "FactPlayerMatch": {"MatchID": "20260408-arsenal-bayern-munchen", "Date": dt.date(2026, 4, 8), "SeasonID": "2025-26",
                        "PlayerID": "harry-kane", "TeamID": "t-bayern-munchen", "OpponentTeamID": "t-arsenal",
                        "CompetitionID": "uefa-champions-league", "Stage": "QF", "IsKnockout": True, "IsVsTop6": True,
                        "Minutes": 90, "Goals": 1, "PenaltyGoals": 0, "Assists": 1, "xG": 0.85, "npxG": 0.85,
                        "xA": 0.32, "Shots": 4, "ShotsOnTarget": 2, "DecisiveGoals": 1, "Rating": 8.4,
                        "TeamGoals": 2, "Result": "W", "xGIncEst": 0.85, "npxGIncEst": 0.85, "IsXgEstimated": False},
    "FactPlayerSeason": {"SeasonID": "2025-26", "PlayerID": "harry-kane", "TeamID": "t-bayern-munchen", "Matches": 50,
                         "Minutes": 4200, "Goals": 40, "PenaltyGoals": 8, "Assists": 10, "xG": 36.5, "npxG": 30.2,
                         "xA": 8.1, "BigStageKnockoutGA": 6, "LeaguePosition": 1, "MinutesWithXg": 3600,
                         "xGIncEst": 42.0, "npxGIncEst": 35.7},
    "FactVoting": {"SeasonID": "2025-26", "PlayerID": "harry-kane", "Rank": 1, "Points": 1000,
                   "VoteSharePct": None, "FirstPlaceVotes": 50},
    "FactPlayerCompetition": {"SeasonID": "2025-26", "PlayerID": "harry-kane", "TeamID": "t-bayern-munchen",
                              "CompetitionID": "uefa-champions-league", "StageReached": "SF", "StageOrder": 6,
                              "MaxStageOrder": 8, "IsWinner": False, "TrophyTier": "Major", "TrophyWeight": 3},
}

README_LINES = [
    ("Contents", "h"),
    ("Tables", "Every sheet except README is an Excel table with the same name as the sheet."),
    ("Origin", "Written by etl/run.py from Wikipedia, SofaScore and data/manual/*.csv."),
    ("Columns", "Header comments hold each column's type, description and source; dropdowns list the allowed values."),
    ("", None),
    ("Relationships", "h"),
    ("DimPlayer[PlayerID]", "1 → * FactPlayerMatch, FactPlayerSeason, FactVoting, FactPlayerCompetition"),
    ("DimSeason[SeasonID]", "1 → * FactPlayerMatch, FactPlayerSeason, FactVoting, FactPlayerCompetition"),
    ("DimTeam[TeamID]", "1 → * FactPlayerMatch[TeamID] (active), FactPlayerMatch[OpponentTeamID] (inactive), FactPlayerSeason[TeamID], FactPlayerCompetition[TeamID]"),
    ("DimCompetition[CompetitionID]", "1 → * FactPlayerMatch, FactPlayerCompetition"),
    ("DimDate[Date]", "1 → * FactPlayerMatch[Date]. DimDate is a DAX calculated table."),
    ("IndexWeights", "No relationships."),
    ("Filter direction", "Single everywhere (dimension → fact)."),
    ("", None),
    ("Definitions", "h"),
    ("Evaluation period", "From 2022 a season (August-July); before 2022 a calendar year. Set in etl/config.yaml."),
    ("2020", "No award was given."),
    ("Points", "Point systems per year in etl/config.yaml (point_systems). 2010–2015: percentages in VoteSharePct."),
    ("DecisiveGoals", "From the final score: in a win by m goals min(goals, m); in a draw all of the player's goals; in a defeat 0."),
    ("IsVsTop6", "Top 6 of the final table of a big-5 league plus the teams in data/manual/top_opponents.csv."),
    ("Rating", "SofaScore match rating; data/manual/ratings.csv overrides it."),
    ("npxG", "xG − 0.79 × (penalty goals + missed penalties)."),
    ("xG coverage", "xG, npxG and xA are empty for matches without xG on SofaScore (most domestic cups, super cups, qualifiers, friendlies)."),
    ("xGIncEst, npxGIncEst", "Season totals with an estimate for matches without xG: non-penalty shots × the player's npxG per shot in matches with xG (shrunk to the nominees' average), +0.79 per penalty goal."),
    ("", None),
    ("Column dictionary", "h"),
]
TEMPLATE_NOTE = ("Template", "Row 2 of each sheet (yellow) is an example row with illustrative values.")

FONT = "Arial"


def empty_tables() -> dict[str, pd.DataFrame]:
    out = {name: pd.DataFrame(columns=[c[0] for c in cols]) for name, (_, _, cols) in TABLES.items()}
    out["IndexWeights"] = DEFAULT_WEIGHTS.copy()
    return out


def example_tables() -> dict[str, pd.DataFrame]:
    """Every table with its example row (IndexWeights: the default weights)."""
    out = {name: pd.DataFrame([row]) for name, row in EXAMPLE_ROWS.items()}
    out["IndexWeights"] = DEFAULT_WEIGHTS.copy()
    return out


def _write_readme(ws, template: bool) -> None:
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 110
    title = "Ballon d'Or: Power BI data model" + (" (template)" if template else "")
    ws.cell(1, 1, title).font = Font(name=FONT, bold=True, size=14)
    lines = list(README_LINES)
    if template:
        lines.insert(4, TEMPLATE_NOTE)
    r = 3
    for a, b in lines:
        if b == "h":
            ws.cell(r, 1, a).font = Font(name=FONT, bold=True, size=12)
        else:
            ws.cell(r, 1, a).font = Font(name=FONT, bold=True)
            c = ws.cell(r, 2, b)
            c.font = Font(name=FONT)
            c.alignment = Alignment(wrap_text=True, vertical="top")
        r += 1
    for name, (desc, src, cols) in TABLES.items():
        ws.cell(r, 1, name).font = Font(name=FONT, bold=True, color="1F4E78")
        ws.cell(r, 2, f"{desc}  Source: {src}").font = Font(name=FONT, italic=True)
        r += 1
        for col, typ, d, _ in cols:
            ws.cell(r, 1, f"   {col}").font = Font(name=FONT)
            ws.cell(r, 2, f"[{typ}] {d}").font = Font(name=FONT)
            r += 1
        r += 1


def _cell_value(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.date()
    if hasattr(v, "item"):  # numpy scalar -> python
        return v.item()
    return v


def build_workbook(tables: dict[str, pd.DataFrame], path: str | Path, template: bool = False) -> Path:
    """template=True: README note about the example rows, data rows highlighted in yellow."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    _write_readme(wb.active, template)
    wb.active.title = "README"

    header_font = Font(name=FONT, bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", start_color="1F4E78")
    body_font = Font(name=FONT)
    example_fill = PatternFill("solid", start_color="FFF2CC")

    for name, (_, src, cols) in TABLES.items():
        ws = wb.create_sheet(name)
        df = tables.get(name, pd.DataFrame(columns=[c[0] for c in cols]))
        df = df.reindex(columns=[c[0] for c in cols])
        for j, (col, typ, desc, opts) in enumerate(cols, 1):
            h = ws.cell(1, j, col)
            h.font, h.fill = header_font, header_fill
            h.comment = Comment(f"[{typ}] {desc}\nSource: {src}", "ETL")
            letter = get_column_letter(j)
            ws.column_dimensions[letter].width = max(14, len(col) + 4)
            if opts:
                dv = DataValidation(type="list", formula1='"' + ",".join(opts) + '"', allow_blank=True)
                ws.add_data_validation(dv)
                dv.add(f"{letter}2:{letter}50000")
        types = [c[1] for c in cols]
        for i, row in enumerate(df.itertuples(index=False), 2):
            for j, v in enumerate(row, 1):
                c = ws.cell(i, j, _cell_value(v))
                c.font = body_font
                if template and name != "IndexWeights":
                    c.fill = example_fill
                if types[j - 1] == "Date":
                    c.number_format = "yyyy-mm-dd"
                elif types[j - 1] == "Decimal":
                    c.number_format = "0.00"
        # an Excel Table needs at least one data row
        last_row = max(2, len(df) + 1)
        ref = f"A1:{get_column_letter(len(cols))}{last_row}"
        table = Table(displayName=name, ref=ref)
        table.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
        ws.add_table(table)
        ws.freeze_panes = "A2"

    wb.save(path)
    return path
