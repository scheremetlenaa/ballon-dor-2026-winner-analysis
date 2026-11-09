"""Pure transformations: raw scraped frames -> model tables. No network access here."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

import pandas as pd

STAGE_ORDER = {"League phase": 1, "Group": 1, "Cup round": 2, "Playoff": 2, "R32": 3,
               "R16": 4, "QF": 5, "SF": 6, "Final": 7, "Winner": 8}
MAX_STAGE_ORDER = STAGE_ORDER["Winner"]
KNOCKOUT_STAGES = {"Cup round", "Playoff", "R32", "R16", "QF", "SF", "Final"}
NATIONAL_TYPES = {"International", "Qualifier"}
NO_RESULT_TYPES = {"Qualifier", "Other"}      # not added to FactPlayerCompetition


# ---------------------------------------------------------------- keys and dates

def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def team_id(name: str) -> str:
    return "t-" + slug(name)


def season_id(year: int) -> str:
    """Award year 2026 -> '2025-26'."""
    return f"{year - 1}-{str(year)[2:]}"


def evaluation_window(year: int, season_based_from: int) -> tuple[dt.date, dt.date]:
    if year >= season_based_from:
        return dt.date(year - 1, 8, 1), dt.date(year, 7, 31)
    return dt.date(year, 1, 1), dt.date(year, 12, 31)


def club_season_of(day: dt.date) -> str:
    """Club season (August-July) of a date: 2025-10-01 -> '2025-2026'."""
    start = day.year if day.month >= 8 else day.year - 1
    return f"{start}-{start + 1}"


def club_seasons_for_window(start: dt.date, end: dt.date) -> list[str]:
    """Club seasons ('2025-2026') that overlap the window."""
    seasons = []
    for y in range(start.year - 1, end.year + 1):
        s0, s1 = dt.date(y, 8, 1), dt.date(y + 1, 7, 31)
        if s0 <= end and s1 >= start:
            seasons.append(f"{y}-{y + 1}")
    return seasons


# ---------------------------------------------------------------- match-level parsing

RESULT_RE = re.compile(r"([WDL])\s*(\d+)\s*[–-]\s*(\d+)(?:\s*\((\d+)\s*[–-]\s*(\d+)\))?")


def parse_result(text) -> tuple[str | None, int | None, int | None, bool | None]:
    """'W 2–1' -> ('W', 2, 1, None); 'D 1–1 (4–3)' -> ('D', 1, 1, True); the last item is the shootout result."""
    m = RESULT_RE.search(str(text))
    if not m:
        return None, None, None, None
    letter, gf, ga, pf, pa = m.groups()
    shootout = None if pf is None else int(pf) > int(pa)
    return letter, int(gf), int(ga), shootout


def clean_team(name) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    return name.strip()


def stage_from_round(round_label, comp_type: str) -> str:
    r = str(round_label or "").lower()
    if comp_type == "League" or "matchweek" in r:
        return "League"
    for fraction, stage in (("1/2", "SF"), ("1/4", "QF"), ("1/8", "R16"), ("1/16", "R32")):
        if r.startswith(fraction):                # '1/8-finals'
            return stage
    if "semi" in r:
        return "SF"
    if "quarter" in r:
        return "QF"
    if "round of 16" in r or "last 16" in r:
        return "R16"
    if "round of 32" in r or "last 32" in r:
        return "R32"
    if "final" in r:
        return "Final"
    if "play-off" in r or "playoff" in r or "knockout round" in r:
        return "Playoff"
    if "league phase" in r or "league stage" in r:
        return "League phase"
    if "group" in r:
        return "Group"
    if comp_type == "Super Cup":
        return "Final"
    if comp_type == "Domestic Cup":
        return "Cup round"
    return "Other"


def decisive_goals(letter, gf, ga, goals) -> int:
    """Approximation from the score: goals without which the result would have been worse."""
    goals = int(goals or 0)
    if letter == "W" and gf is not None:
        return min(goals, gf - ga)
    if letter == "D":
        return goals
    return 0


def comp_attrs(label: str, competitions: dict) -> dict:
    cfg = competitions.get(label)
    if cfg is None:
        return {"name": label, "type": "Other", "big_stage": False, "tier": "Minor", "weight": 0, "known": False}
    return {**cfg, "known": True}


def build_match_rows(raw: pd.DataFrame, player_id: str, year: int, competitions: dict,
                     top_opponents: dict[str, set[str]]) -> pd.DataFrame:
    """raw: one player's match rows from sofascore.match_row, filtered to the evaluation window.

    top_opponents: club season ('2025-2026') or SeasonID ('2025-26') -> set of team names.
    Returns FactPlayerMatch columns plus helper columns prefixed with '_'.
    """
    rows = []
    sid = season_id(year)
    for r in raw.itertuples(index=False):
        attrs = comp_attrs(r.Comp, competitions)
        letter, gf, ga, shootout = parse_result(r.Result)
        team, opp = clean_team(r.Squad), clean_team(r.Opponent)
        stage = stage_from_round(r.Round, attrs["type"])
        fs = club_season_of(r.Date)
        tops = top_opponents.get(fs, set()) | top_opponents.get(sid, set())
        goals = int(r.Goals or 0) if pd.notna(r.Goals) else 0
        rows.append({
            "MatchID": f"{r.Date:%Y%m%d}-" + "-".join(sorted([slug(team or ''), slug(opp or '')])),
            "Date": r.Date,
            "SeasonID": sid,
            "PlayerID": player_id,
            "TeamID": team_id(team) if team else None,
            "OpponentTeamID": team_id(opp) if opp else None,
            "CompetitionID": slug(attrs["name"]),
            "Stage": stage,
            "IsKnockout": stage in KNOCKOUT_STAGES,
            "IsVsTop6": opp in tops,
            "Minutes": r.Minutes,
            "Goals": goals,
            "PenaltyGoals": r.PenaltyGoals,
            "Assists": r.Assists,
            "xG": r.xG, "npxG": r.npxG, "xA": r.xA,
            "Shots": r.Shots, "ShotsOnTarget": r.ShotsOnTarget,
            "DecisiveGoals": decisive_goals(letter, gf, ga, goals),
            "Rating": getattr(r, "Rating", None),
            "TeamGoals": gf,
            "Result": letter,
            "_Comp": r.Comp, "_CompName": attrs["name"], "_CompType": attrs["type"],
            "_BigStage": bool(attrs["big_stage"]), "_Team": team, "_Opponent": opp,
            "_ClubSeason": fs, "_WonShootout": shootout,
        })
    return pd.DataFrame(rows)


PENALTY_XG = 0.79        # xG of a penalty (Opta)
XG_PRIOR_SHOTS = 20      # shrinks a player's npxG per shot towards the season average


def fill_xg(m: pd.DataFrame) -> pd.DataFrame:
    """Add xGIncEst, npxGIncEst and IsXgEstimated to FactPlayerMatch rows.

    Where the source has xG, the columns repeat it. Where it has none but shots are known,
    npxG is non-penalty shots × the player's npxG per shot in the matches with xG of the same season,
    shrunk towards the average of all nominees (XG_PRIOR_SHOTS); xG adds 0.79 per penalty goal.
    """
    m = m.copy()
    np_shots = (m["Shots"] - m["PenaltyGoals"].fillna(0)).clip(lower=0)
    covered = m["npxG"].notna() & m["Shots"].notna()
    cov = pd.DataFrame({"SeasonID": m["SeasonID"], "PlayerID": m["PlayerID"],
                        "npxG": m["npxG"].where(covered, 0.0), "shots": np_shots.where(covered, 0.0)})
    season = cov.groupby("SeasonID")[["npxG", "shots"]].sum()
    pool = (season["npxG"] / season["shots"].where(season["shots"] > 0)).rename("pool")
    player = cov.groupby(["SeasonID", "PlayerID"])[["npxG", "shots"]].sum().join(pool, on="SeasonID")
    player["rate"] = (player["npxG"] + XG_PRIOR_SHOTS * player["pool"]) / (player["shots"] + XG_PRIOR_SHOTS)
    rate = m.join(player["rate"], on=["SeasonID", "PlayerID"])["rate"]

    estimate = np_shots * rate
    missing = m["npxG"].isna() & estimate.notna()
    m["npxGIncEst"] = m["npxG"].where(~missing, estimate)
    m["xGIncEst"] = m["xG"].where(~missing, estimate + PENALTY_XG * m["PenaltyGoals"].fillna(0))
    m["IsXgEstimated"] = missing
    return m


def filter_window(raw: pd.DataFrame, start: dt.date, end: dt.date) -> pd.DataFrame:
    if raw.empty:
        return raw
    out = raw[(raw["Date"] >= start) & (raw["Date"] <= end)]
    return out.drop_duplicates(["Date", "Opponent"]).sort_values("Date").reset_index(drop=True)


# ---------------------------------------------------------------- season aggregates

def _sum(series):
    return series.sum(min_count=1)


def main_club(m: pd.DataFrame) -> str | None:
    clubs = m[~m["_CompType"].isin(NATIONAL_TYPES | {"Other"})]
    if clubs.empty:
        return None
    return clubs.groupby("_Team")["Minutes"].sum().idxmax()


def league_position(m: pd.DataFrame, club: str | None, standings: dict) -> int | None:
    """standings: (league label, club season) -> DataFrame[Rk, Squad]."""
    if club is None:
        return None
    lg = m[(m["_Team"] == club) & (m["_CompType"] == "League")]
    if lg.empty:
        return None
    best = lg.groupby(["_Comp", "_ClubSeason"])["Minutes"].sum().idxmax()
    table = standings.get(best)
    if table is None or table.empty:
        return None
    hit = table.loc[table["Squad"] == club, "Rk"]
    return int(hit.iloc[0]) if len(hit) else None


def aggregate_season(m: pd.DataFrame, player_id: str, year: int, standings: dict) -> dict:
    """m: one player's FactPlayerMatch rows for one award year, after fill_xg."""
    club = main_club(m)
    big_ko = m[m["IsKnockout"] & m["_BigStage"]]
    return {
        "SeasonID": season_id(year),
        "PlayerID": player_id,
        "TeamID": team_id(club) if club else None,
        "Matches": int(len(m)),
        "Minutes": _sum(m["Minutes"]),
        "Goals": _sum(m["Goals"]),
        "PenaltyGoals": _sum(m["PenaltyGoals"]),
        "Assists": _sum(m["Assists"]),
        "xG": _sum(m["xG"]),
        "npxG": _sum(m["npxG"]),
        "xA": _sum(m["xA"]),
        "MinutesWithXg": m.loc[m["xG"].notna(), "Minutes"].sum(),
        "xGIncEst": _sum(m["xGIncEst"]),
        "npxGIncEst": _sum(m["npxGIncEst"]),
        "BigStageKnockoutGA": int(big_ko["Goals"].sum() + big_ko["Assists"].fillna(0).sum()),
        "LeaguePosition": league_position(m, club, standings),
    }


def competition_results(m: pd.DataFrame, player_id: str, year: int, competitions: dict,
                        standings: dict) -> list[dict]:
    out = []
    for (comp, team, fs), g in m.groupby(["_Comp", "_Team", "_ClubSeason"]):
        attrs = comp_attrs(comp, competitions)
        if attrs["type"] in NO_RESULT_TYPES:
            continue
        row = {"SeasonID": season_id(year), "PlayerID": player_id, "TeamID": team_id(team),
               "CompetitionID": slug(attrs["name"]), "TrophyTier": attrs["tier"],
               "TrophyWeight": attrs["weight"]}
        if attrs["type"] == "League":
            table = standings.get((comp, fs))
            hit = None if table is None else table.loc[table["Squad"] == team, "Rk"]
            if hit is None or not len(hit):
                row.update(StageReached="League", StageOrder=None, MaxStageOrder=None, IsWinner=False)
            else:
                pos, n = int(hit.iloc[0]), len(table)
                row.update(StageReached="Winner" if pos == 1 else "League",
                           StageOrder=n - pos + 1, MaxStageOrder=n, IsWinner=pos == 1)
        else:
            finals = g[g["Stage"] == "Final"]
            won = bool(((finals["Result"] == "W") | (finals["_WonShootout"] == True)).any())  # noqa: E712
            played = [s for s in g["Stage"] if s in STAGE_ORDER]
            best = max(played, key=STAGE_ORDER.get) if played else "Group"
            stage = "Winner" if won else best
            row.update(StageReached=stage, StageOrder=STAGE_ORDER[stage],
                       MaxStageOrder=MAX_STAGE_ORDER, IsWinner=won)
        out.append(row)
    return out


# ---------------------------------------------------------------- voting helpers

def point_system(year: int, systems: list[dict]) -> dict:
    for s in systems:
        if s["from"] <= year <= s["to"]:
            return s
    return {"max_points": None, "ballot_total": None}


def estimate_voters(points: pd.Series, ballot_total) -> int | None:
    total = points.dropna().sum()
    if not ballot_total or total == 0:
        return None
    return int(round(total / ballot_total))


def position_group(position) -> str | None:
    if not isinstance(position, str) or len(position) < 2:
        return None
    g = position[:2]
    return g if g in {"FW", "MF", "DF", "GK"} else None
