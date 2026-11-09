"""Builds the model workbook: Wikipedia voting, SofaScore matches and manual inputs -> data/processed/BallonDor_Data.xlsx."""
from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import yaml

from . import transform as T
from .fetch import Blocked, Fetcher
from .schema import DEFAULT_WEIGHTS, build_workbook, empty_tables, example_tables
from .sources import sofascore, wikipedia

log = logging.getLogger("etl")
ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / "data" / "manual"

PLAYER_COLS = ["PlayerName", "SofascoreID", "PositionGroup", "BirthDate", "Nationality"]


def read_manual(name: str, columns: list[str]) -> pd.DataFrame:
    path = MANUAL / name
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_csv(path, dtype=str, keep_default_na=False).replace("", pd.NA)
    return df.reindex(columns=columns)


# ---------------------------------------------------------------- voting and players

def load_all_voting(fetcher: Fetcher, years: list[int], refresh: bool = False) -> pd.DataFrame:
    frames = [v for y in years if (v := wikipedia.load_voting(fetcher, y, refresh)) is not None]
    if not frames:
        raise SystemExit("No voting data loaded")
    df = pd.concat(frames, ignore_index=True)
    df["PlayerID"] = df["PlayerName"].map(T.slug)
    return df


def save_player_ids(found: dict[str, tuple[str, str]]) -> None:
    """found: PlayerID -> (PlayerName, SofaScore ID). Adds or fills rows in data/manual/players.csv."""
    if not found:
        return
    manual = read_manual("players.csv", PLAYER_COLS)
    slugs = manual["PlayerName"].map(T.slug)
    for pid, (name, value) in found.items():
        hit = slugs == pid
        if hit.any():
            manual.loc[hit & manual["SofascoreID"].isna(), "SofascoreID"] = value
        else:
            manual = pd.concat([manual, pd.DataFrame([{"PlayerName": name, "SofascoreID": value}])],
                               ignore_index=True)
    MANUAL.mkdir(parents=True, exist_ok=True)
    manual.reindex(columns=PLAYER_COLS).to_csv(MANUAL / "players.csv", index=False)
    log.info("saved %d SofascoreID values to data/manual/players.csv", len(found))


def manual_ids() -> dict[str, str]:
    manual = read_manual("players.csv", PLAYER_COLS)
    return {T.slug(n): str(i) for n, i in zip(manual["PlayerName"], manual["SofascoreID"])
            if pd.notna(n) and pd.notna(i)}


def top_opponent_sets(standings: dict, manual: pd.DataFrame) -> dict[str, set[str]]:
    """Club season or SeasonID -> top-6 teams of every loaded league table plus data/manual/top_opponents.csv."""
    tops: dict[str, set[str]] = {}
    for (_, fs), table in standings.items():
        tops.setdefault(fs, set()).update(table.loc[table["Rk"] <= 6, "Squad"])
    for year, team in zip(manual["BallonDorYear"], manual["TeamName"]):
        if pd.notna(year) and pd.notna(team):
            tops.setdefault(T.season_id(int(year)), set()).add(team)
    return tops


# ---------------------------------------------------------------- main

def run(cfg: dict, years: list[int], offline: bool, voting_only: bool) -> dict[str, pd.DataFrame]:
    fetcher = Fetcher(ROOT / cfg["cache_dir"], cfg["request_delay_seconds"], offline=offline,
                      client="requests" if voting_only else "browser",
                      browser_profile=ROOT / cfg["browser_profile"],
                      browser_options={"chrome_path": cfg.get("chrome_path")})
    try:
        return _run(cfg, years, voting_only, fetcher)
    finally:
        fetcher.close()


def _run(cfg: dict, years: list[int], voting_only: bool, fetcher: Fetcher) -> dict[str, pd.DataFrame]:
    competitions = cfg["competitions"]

    voting = load_all_voting(fetcher, years, refresh=bool(cfg.get("refresh_voting")))
    tables = empty_tables()

    seasons = []
    for y in sorted(voting["BallonDorYear"].unique()):
        y = int(y)
        start, end = T.evaluation_window(y, cfg["season_based_from"])
        ps = T.point_system(y, cfg["point_systems"])
        voters = cfg.get("voters_count", {}).get(y) or T.estimate_voters(
            voting.loc[voting["BallonDorYear"] == y, "Points"], ps["ballot_total"])
        seasons.append({"SeasonID": T.season_id(y), "BallonDorYear": y, "StartDate": start,
                        "EndDate": end, "VotersCount": voters, "MaxPointsPerBallot": ps["max_points"]})
    tables["DimSeason"] = pd.DataFrame(seasons)

    fpv = read_manual("first_place_votes.csv", ["BallonDorYear", "PlayerName", "FirstPlaceVotes"])
    fpv = fpv.dropna(subset=["BallonDorYear", "PlayerName"]).assign(
        BallonDorYear=lambda d: d["BallonDorYear"].astype(int),
        PlayerID=lambda d: d["PlayerName"].map(T.slug),
        FirstPlaceVotes=lambda d: pd.to_numeric(d["FirstPlaceVotes"], errors="coerce"))
    fv = voting.merge(fpv[["BallonDorYear", "PlayerID", "FirstPlaceVotes"]], how="left",
                      on=["BallonDorYear", "PlayerID"])
    fv["SeasonID"] = fv["BallonDorYear"].astype(int).map(T.season_id)
    tables["FactVoting"] = fv

    players = voting.drop_duplicates("PlayerID")[["PlayerID", "PlayerName"]].copy()

    if voting_only:
        tables["DimPlayer"] = players
        return tables

    match_years = set(cfg["match_level_years"])
    picks = []
    for y, g in voting.groupby("BallonDorYear"):
        n = cfg["top_n_nominees"]["match_level_years" if y in match_years else "other_years"]
        picks += [(int(y), r.PlayerID, r.PlayerName) for r in g.sort_values("Rank").head(n).itertuples()]
    windows = {y: T.evaluation_window(y, cfg["season_based_from"]) for y in {y for y, _, _ in picks}}
    ids, meta, standings, logs = collect_sofascore(fetcher, cfg, picks, windows)
    logs, standings = rename_teams(logs, standings, cfg.get("team_names") or {})
    tops = top_opponent_sets(standings, read_manual("top_opponents.csv", ["BallonDorYear", "TeamName"]))

    match_frames = []
    for y, pid, name in picks:
        raw = logs.get((y, pid))
        if raw is None:
            continue
        if raw.empty:
            log.warning("%s %s: no matches found in %s..%s", y, name, *windows[y])
            continue
        match_frames.append(T.build_match_rows(raw, pid, y, competitions, tops))
        log.info("%s %s: %d matches", y, name, len(match_frames[-1]))

    all_matches = T.fill_xg(pd.concat(match_frames, ignore_index=True)) if match_frames else pd.DataFrame()
    season_rows, comp_rows = [], []
    for (sid, pid), m in (all_matches.groupby(["SeasonID", "PlayerID"], sort=False) if not all_matches.empty else []):
        y = int(sid[:4]) + 1
        season_rows.append(T.aggregate_season(m, pid, y, standings))
        comp_rows += T.competition_results(m, pid, y, competitions, standings)
        est = int(m["IsXgEstimated"].sum())
        if est:
            log.info("%s %s: xG estimated from shots in %d of %d matches", y, pid, est, len(m))

    unknown = Counter(c for c in all_matches.get("_Comp", []) if c not in competitions)
    for comp, n in unknown.most_common():
        log.warning("competition %r (%d matches) is not in config.yaml, loaded as type Other", comp, n)

    fm = all_matches[all_matches["SeasonID"].isin({T.season_id(y) for y in match_years})].copy() \
        if not all_matches.empty else pd.DataFrame(columns=["PlayerID", "Date"])
    ratings = read_manual("ratings.csv", ["Date", "PlayerName", "Rating"]).dropna()
    if not ratings.empty and not fm.empty:
        ratings = ratings.assign(PlayerID=ratings["PlayerName"].map(T.slug),
                                 Date=pd.to_datetime(ratings["Date"]).dt.date,
                                 Rating=pd.to_numeric(ratings["Rating"], errors="coerce"))
        fm = fm.merge(ratings[["PlayerID", "Date", "Rating"]].rename(columns={"Rating": "_Manual"}),
                      how="left", on=["PlayerID", "Date"])
        fm["Rating"] = fm["_Manual"].combine_first(pd.to_numeric(fm["Rating"], errors="coerce"))
        fm = fm.drop(columns="_Manual")
    tables["FactPlayerMatch"] = fm

    tables["FactPlayerSeason"] = pd.DataFrame(season_rows)
    tables["FactPlayerCompetition"] = apply_competition_overrides(pd.DataFrame(comp_rows))

    tables["DimPlayer"] = build_dim_player(players, meta, ids)
    tables["DimTeam"] = build_dim_team(all_matches, standings, competitions)
    tables["DimCompetition"] = build_dim_competition(all_matches)
    weights = cfg.get("index_weights")
    tables["IndexWeights"] = (pd.DataFrame({"Component": list(weights), "Weight": list(weights.values())})
                              if weights else DEFAULT_WEIGHTS.copy())
    return tables


# ---------------------------------------------------------------- SofaScore

def collect_sofascore(fetcher: Fetcher, cfg: dict, picks: list, windows: dict):
    """Returns (ids, meta, standings, logs):
    ids        PlayerID -> SofaScore player ID
    meta       PlayerID -> {"Position", "PositionGroup", "BirthDate", "Nationality"}
    standings  (league label, '2025-2026') -> DataFrame[Rk, Squad]
    logs       (award year, PlayerID) -> match rows filtered to the evaluation window
    """
    aliases = cfg.get("sofascore_competitions") or {}
    competitions = cfg["competitions"]

    known = manual_ids()
    ids, added = {}, {}
    for _, pid, name in picks:
        if pid in ids:
            continue
        found = known.get(pid) or sofascore.search_player(fetcher, name)
        if found:
            ids[pid] = found
            if pid not in known:
                added[pid] = (name, found)
        else:
            log.warning("SofaScore: %s not found", name)
    save_player_ids(added)

    meta = {pid: sofascore.parse_player(sofascore.get_json(fetcher, f"/player/{sid}")) for pid, sid in ids.items()}

    standings = {}
    club_seasons = {s for w in windows.values() for s in T.club_seasons_for_window(*w)}
    for fs in sorted(club_seasons):
        for label, lg in cfg["leagues"].items():
            standings[(label, fs)] = sofascore.load_standings(fetcher, lg["sofascore_id"], fs)

    logs, seen = {}, {}
    for pid, sid in ids.items():
        player_windows = [windows[y] for y, p, _ in picks if p == pid]
        events = sofascore.load_player_events(fetcher, sid, min(s for s, _ in player_windows))
        seen.update(sofascore.tournaments_seen(events))
        raw = sofascore.load_matchlog(fetcher, sid, events, aliases, competitions, player_windows)
        for y, p, _ in picks:
            if p == pid:
                logs[(y, pid)] = T.filter_window(raw, *windows[y]) if not raw.empty else raw
    for ut in sorted(seen.values(), key=lambda t: str(t["name"])):
        label = sofascore.competition_label(ut, aliases, competitions)
        log.info("SofaScore tournament %6s %-30s %-14s -> %s%s", ut["id"], ut["name"], ut["category"] or "",
                 label, "" if label in competitions else "  (not in config.yaml)")
    return ids, meta, standings, logs


# ---------------------------------------------------------------- tables

def rename_teams(logs: dict, standings: dict, names: dict) -> tuple[dict, dict]:
    """Applies `team_names` from config.yaml to match rows and league tables before team IDs are built."""
    if not names:
        return logs, standings
    logs = {k: v.assign(Squad=v["Squad"].replace(names), Opponent=v["Opponent"].replace(names))
            if not v.empty else v for k, v in logs.items()}
    standings = {k: v.assign(Squad=v["Squad"].replace(names)) for k, v in standings.items()}
    return logs, standings


def apply_competition_overrides(fc: pd.DataFrame) -> pd.DataFrame:
    """Updates or adds FactPlayerCompetition rows from data/manual/competition_overrides.csv."""
    cols = ["BallonDorYear", "PlayerName", "CompetitionName", "TeamName", "StageReached", "IsWinner"]
    ov = read_manual("competition_overrides.csv", cols).dropna(subset=["BallonDorYear", "PlayerName", "CompetitionName"])
    for r in ov.itertuples(index=False):
        key = {"SeasonID": T.season_id(int(r.BallonDorYear)), "PlayerID": T.slug(r.PlayerName),
               "CompetitionID": T.slug(r.CompetitionName)}
        mask = pd.Series(True, index=fc.index)
        for k, v in key.items():
            mask &= fc.get(k, pd.Series(dtype=str)) == v
        stage = r.StageReached if pd.notna(r.StageReached) else None
        winner = str(r.IsWinner).upper() == "TRUE" if pd.notna(r.IsWinner) else None
        if not mask.any():
            row = {**key, "TeamID": T.team_id(r.TeamName) if pd.notna(r.TeamName) else None,
                   "StageReached": stage, "StageOrder": T.STAGE_ORDER.get(stage),
                   "MaxStageOrder": T.MAX_STAGE_ORDER, "IsWinner": bool(winner)}
            fc = pd.concat([fc, pd.DataFrame([row])], ignore_index=True)
            continue
        if stage:
            fc.loc[mask, "StageReached"] = stage
            if stage in T.STAGE_ORDER:
                fc.loc[mask, ["StageOrder", "MaxStageOrder"]] = [T.STAGE_ORDER[stage], T.MAX_STAGE_ORDER]
        if winner is not None:
            fc.loc[mask, "IsWinner"] = winner
    return fc


def build_dim_player(players: pd.DataFrame, meta: dict, ids: dict) -> pd.DataFrame:
    """Values in data/manual/players.csv win over SofaScore."""
    manual = read_manual("players.csv", PLAYER_COLS).dropna(subset=["PlayerName"])
    manual = manual.assign(PlayerID=manual["PlayerName"].map(T.slug)).drop_duplicates("PlayerID").set_index("PlayerID")

    def pick(pid, column, fallback=None):
        v = manual[column].get(pid) if column in manual else None
        return v if v is not None and pd.notna(v) else fallback

    rows = []
    for r in players.itertuples(index=False):
        m = meta.get(r.PlayerID, {})
        birth = pick(r.PlayerID, "BirthDate", m.get("BirthDate"))
        rows.append({
            "PlayerID": r.PlayerID, "PlayerName": r.PlayerName,
            "Nationality": pick(r.PlayerID, "Nationality", m.get("Nationality")),
            "Position": m.get("Position"),
            "PositionGroup": pick(r.PlayerID, "PositionGroup", m.get("PositionGroup") or T.position_group(m.get("Position"))),
            "BirthDate": pd.to_datetime(birth).date() if birth is not None and pd.notna(birth) else None,
            "SofascoreID": ids.get(r.PlayerID),
        })
    return pd.DataFrame(rows)


def build_dim_team(m: pd.DataFrame, standings: dict, competitions: dict) -> pd.DataFrame:
    cols = ["TeamID", "TeamName", "TeamType", "League"]
    if m.empty:
        return pd.DataFrame(columns=cols)
    # national teams: teams of international and qualifier matches and of "Friendlies" (club friendlies have another name)
    national_rows = m["_CompType"].isin(T.NATIONAL_TYPES) | (m["_CompName"] == "Friendlies")
    national = set(m.loc[national_rows, "_Team"]) | set(m.loc[national_rows, "_Opponent"])
    league_of = {}
    league_rows = m[m["_CompType"] == "League"]
    for side in ("_Team", "_Opponent"):
        league_of.update(zip(league_rows[side], league_rows["_CompName"]))
    for (label, _), table in standings.items():
        for squad in table["Squad"]:
            league_of[squad] = competitions.get(label, {}).get("name", label)
    names = sorted({t for t in pd.concat([m["_Team"], m["_Opponent"]]).dropna()})
    return pd.DataFrame([{"TeamID": T.team_id(n), "TeamName": n,
                          "TeamType": "National" if n in national else "Club",
                          "League": None if n in national else league_of.get(n)} for n in names],
                        columns=cols)


def build_dim_competition(m: pd.DataFrame) -> pd.DataFrame:
    if m.empty:
        return pd.DataFrame()
    d = m.drop_duplicates("CompetitionID")
    return pd.DataFrame({"CompetitionID": d["CompetitionID"], "CompetitionName": d["_CompName"],
                         "CompetitionType": d["_CompType"], "IsBigStage": d["_BigStage"]})


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(ROOT / "etl" / "config.yaml"))
    ap.add_argument("--years", type=int, nargs="*", help="award years (default: all in config)")
    ap.add_argument("--out", help="output .xlsx (default: config.output)")
    ap.add_argument("--offline", action="store_true", help="use cached responses only")
    ap.add_argument("--voting-only", action="store_true", help="load Wikipedia voting only")
    ap.add_argument("--refresh-voting", action="store_true", help="download the Wikipedia voting pages again")
    ap.add_argument("--template", metavar="PATH", help="write the workbook with one example row per table")
    ap.add_argument("--log-file", metavar="PATH", help="also write the log to this file")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, handlers=handlers, force=True,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if args.template:
        log.info("template written to %s", build_workbook(example_tables(), args.template, template=True))
        return

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    years = args.years or cfg["years"]
    if args.refresh_voting:
        cfg["refresh_voting"] = True
    try:
        tables = run(cfg, years, args.offline, args.voting_only)
    except Blocked as exc:
        log.error("403 Forbidden: %s", exc)
        sys.exit(2)
    out = Path(args.out or ROOT / cfg["output"])
    build_workbook(tables, out)
    for name, df in tables.items():
        log.info("%-22s %6d rows", name, len(df))
    log.info("written %s", out)


if __name__ == "__main__":
    main()
