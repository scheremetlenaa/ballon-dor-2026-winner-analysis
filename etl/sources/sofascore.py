"""SofaScore API: a player's matches in all competitions, his statistics per match, player data and league tables.

Matches: `/player/{id}/events/last/{page}`. Statistics in a match: `/event/{id}/lineups` (minutes, goals,
assists, xG, xA, shots, rating). Penalty goals: `/event/{id}/incidents`, requested only when the player scored.
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import logging
from urllib.parse import quote

import pandas as pd

from .. import transform as T
from ..fetch import Blocked, Fetcher, NotFound

log = logging.getLogger(__name__)

BASE = "https://www.sofascore.com"
API = BASE + "/api/v1"
JSON_HEADERS = {"Accept": "application/json"}

FINISHED_CODES = {100, 110, 120}       # ended, after extra time, after penalties
PENALTY_XG = 0.79                      # xG of a penalty (Opta), used to estimate npxG
MAX_EVENT_PAGES = 40                   # ~30 matches per page
POSITION_GROUPS = {"F": "FW", "M": "MF", "D": "DF", "G": "GK"}


def get_json(fetcher: Fetcher, path: str):
    """GET an API path; None for 404 or an answer that is not JSON. Raises Blocked for 403."""
    try:
        _, text = fetcher.get(API + path, headers=JSON_HEADERS)
    except NotFound:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        log.warning("SofaScore: not JSON at %s", path)
        return None
    err = data.get("error") if isinstance(data, dict) else None
    if err:
        if err.get("code") == 403:
            raise Blocked(API + path)
        return None
    return data


def _date(ts) -> dt.date | None:
    return dt.datetime.fromtimestamp(int(ts), tz=dt.timezone.utc).date() if ts is not None else None


# ---------------------------------------------------------------- players

def find_player(name: str, candidates: list[dict]) -> dict | None:
    """Candidate whose name matches `name`: same slug, then a slug that extends it, then the closest slug."""
    by_slug = {}
    for p in candidates:
        by_slug.setdefault(T.slug(p["player_name"]), p)
    s = T.slug(name)
    if s in by_slug:
        return by_slug[s]
    starts = [k for k in by_slug if k.startswith(s + "-") or s.startswith(k + "-")]
    if len(starts) == 1:
        return by_slug[starts[0]]
    close = difflib.get_close_matches(s, list(by_slug), n=1, cutoff=0.85)
    return by_slug[close[0]] if close else None


def search_player(fetcher: Fetcher, name: str) -> str | None:
    """SofaScore player ID for a name (best name match, else the first search result), or None."""
    data = get_json(fetcher, f"/search/all?q={quote(name)}&page=0") or {}
    players = [r["entity"] for r in data.get("results", [])
               if r.get("type") == "player" and isinstance(r.get("entity"), dict) and "id" in r["entity"]]
    if not players:
        return None
    hit = find_player(name, [{"id": str(p["id"]), "player_name": p.get("name", "")} for p in players])
    if hit:
        return hit["id"]
    first = players[0]
    log.info("SofaScore search for %r: first result %s", name, first.get("name"))
    return str(first["id"])


def parse_player(data: dict | None) -> dict:
    p = (data or {}).get("player") or {}
    group = POSITION_GROUPS.get(p.get("position"))
    return {"Position": group, "PositionGroup": group, "BirthDate": _date(p.get("dateOfBirthTimestamp")),
            "Nationality": (p.get("country") or {}).get("name")}


def load_player_events(fetcher: Fetcher, player_id: str, since: dt.date) -> list[dict]:
    """The player's matches, oldest first. Pages are read newest first until one starts before `since`."""
    events: dict[int, dict] = {}
    for page in range(MAX_EVENT_PAGES):
        data = get_json(fetcher, f"/player/{player_id}/events/last/{page}")
        if not data or not data.get("events"):
            break
        for e in data["events"]:
            events[e["id"]] = e
        oldest = min(_date(e["startTimestamp"]) for e in data["events"])
        if not data.get("hasNextPage") or oldest < since:
            break
    return sorted(events.values(), key=lambda e: e["startTimestamp"])


# ---------------------------------------------------------------- competitions and rounds

def competition_label(unique_tournament: dict, aliases: dict, competitions: dict) -> str:
    """SofaScore tournament -> competition label of config.yaml.

    Looks up `sofascore_competitions` (ID, then name), then the labels and names of `competitions`;
    otherwise returns the SofaScore name.
    """
    tid, name = unique_tournament.get("id"), unique_tournament.get("name") or "Unknown"
    for key in (tid, str(tid), name):
        if key in aliases:
            return aliases[key]
    for label, attrs in competitions.items():
        if T.slug(name) in (T.slug(label), T.slug(attrs.get("name", ""))):
            return label
    return name


def round_label(event: dict, comp_type: str) -> str:
    """Round text in the form transform.stage_from_round parses."""
    info = event.get("roundInfo") or {}
    if info.get("name"):
        return info["name"]                       # 'Quarterfinals', 'Round of 16', 'Final', 'Playoff round'
    stage = (event.get("tournament") or {}).get("name") or ""
    if "group" in stage.lower():
        return stage                              # 'World Championship, Group A'
    if comp_type == "League":
        return f"Matchweek {info.get('round', '')}".strip()
    if comp_type == "Continental":
        return "League phase"                     # numbered rounds without a name
    if comp_type == "Super Cup":
        return "Final"
    return f"Round {info['round']}" if info.get("round") else ""


# ---------------------------------------------------------------- one match

def _score(side: dict) -> int | None:
    v = side.get("display", side.get("current"))
    return int(v) if v is not None else None


def _lineup_entry(player_id: str, lineups: dict | None):
    """('home' | 'away', line-up entry), or (None, None) if the player is not in the line-ups."""
    for side in ("home", "away"):
        for entry in ((lineups or {}).get(side) or {}).get("players", []):
            if str((entry.get("player") or {}).get("id")) == str(player_id):
                return side, entry
    return None, None


def _has_xg(event: dict, lineups: dict | None) -> bool:
    """Whether the match has xG: the event's `hasXg` flag, else any player in the line-ups with `expectedGoals`."""
    if "hasXg" in event:
        return bool(event["hasXg"])
    return any("expectedGoals" in (entry.get("statistics") or {})
               for side in ("home", "away") for entry in ((lineups or {}).get(side) or {}).get("players", []))


def penalty_goals(incidents: dict | None, player_id: str) -> int | None:
    if incidents is None:
        return None
    return sum(1 for i in incidents.get("incidents", [])
               if i.get("incidentType") == "goal" and i.get("incidentClass") == "penalty"
               and str((i.get("player") or {}).get("id")) == str(player_id))


def match_row(event: dict, lineups: dict | None, incidents: dict | None, player_id: str,
              comp: str, comp_type: str) -> dict | None:
    """The player's row for one match (input of transform.build_match_rows), or None if he did not play.

    `incidents` gives the penalty goals and is needed only when the player scored.
    """
    side, entry = _lineup_entry(player_id, lineups)
    stats = (entry or {}).get("statistics") or {}
    minutes = stats.get("minutesPlayed")
    if side is None or not minutes:
        return None
    home = side == "home"
    team, opp = (event["homeTeam"], event["awayTeam"]) if home else (event["awayTeam"], event["homeTeam"])
    hs, as_ = event.get("homeScore") or {}, event.get("awayScore") or {}
    gf, ga = (_score(hs), _score(as_)) if home else (_score(as_), _score(hs))
    if gf is None or ga is None:
        return None
    letter = "W" if gf > ga else "D" if gf == ga else "L"
    result = f"{letter} {gf}–{ga}"
    if hs.get("penalties") is not None and as_.get("penalties") is not None:
        pf, pa = (hs["penalties"], as_["penalties"]) if home else (as_["penalties"], hs["penalties"])
        result += f" ({pf}–{pa})"

    goals = int(stats.get("goals", 0))
    pens = penalty_goals(incidents, player_id) if goals else 0
    has_xg = _has_xg(event, lineups)
    nan = float("nan")
    xg = float(stats.get("expectedGoals", 0.0)) if has_xg else nan
    npxg = nan
    if has_xg and pens is not None:
        npxg = max(xg - PENALTY_XG * (pens + int(stats.get("penaltyMiss", 0))), 0.0)
    return {
        "Date": _date(event["startTimestamp"]),
        "Comp": comp,
        "Round": round_label(event, comp_type),
        "Venue": "Home" if home else "Away",
        "Result": result,
        "Squad": team["name"],
        "Opponent": opp["name"],
        "Minutes": float(minutes),
        "Goals": goals,
        "Assists": float(stats.get("goalAssist", 0)),
        "PenaltyGoals": float(pens) if pens is not None else nan,
        "Shots": float(stats.get("totalShots", 0)),
        "ShotsOnTarget": float(stats.get("onTargetScoringAttempt", 0)),
        "xG": xg,
        "npxG": npxg,
        "xA": float(stats.get("expectedAssists", 0.0)) if has_xg else nan,
        "Rating": float(stats["rating"]) if stats.get("rating") is not None else nan,
        "_SofascoreEventID": event["id"],
    }


def load_matchlog(fetcher: Fetcher, player_id: str, events: list[dict], aliases: dict,
                  competitions: dict, windows: list[tuple[dt.date, dt.date]]) -> pd.DataFrame:
    """Rows for the finished events inside any of `windows`."""
    rows, no_lineup = [], 0
    for e in events:
        day = _date(e["startTimestamp"])
        if (e.get("status") or {}).get("code") not in FINISHED_CODES:
            continue
        if not any(s <= day <= t for s, t in windows):
            continue
        comp = competition_label((e.get("tournament") or {}).get("uniqueTournament") or {}, aliases, competitions)
        comp_type = T.comp_attrs(comp, competitions)["type"]
        lineups = get_json(fetcher, f"/event/{e['id']}/lineups")
        if lineups is None:
            no_lineup += 1
            continue
        row = match_row(e, lineups, None, player_id, comp, comp_type)
        if row is not None and row["Goals"]:
            row = match_row(e, lineups, get_json(fetcher, f"/event/{e['id']}/incidents"),
                            player_id, comp, comp_type)
        if row is not None:
            rows.append(row)
    if no_lineup:
        log.info("SofaScore player %s: %d matches without line-ups skipped", player_id, no_lineup)
    return pd.DataFrame(rows)


def tournaments_seen(events: list[dict]) -> dict[int, dict]:
    """Tournament ID -> {'id', 'name', 'category'} of the events."""
    out = {}
    for e in events:
        ut = (e.get("tournament") or {}).get("uniqueTournament") or {}
        if ut.get("id") is not None:
            out[ut["id"]] = {"id": ut["id"], "name": ut.get("name"), "category": (ut.get("category") or {}).get("name")}
    return out


# ---------------------------------------------------------------- league tables

def season_year(club_season: str) -> str:
    """'2025-2026' -> '25/26', the season label SofaScore uses for leagues."""
    a, b = club_season.split("-")
    return f"{a[2:]}/{b[2:]}"


def load_standings(fetcher: Fetcher, tournament_id: int, club_season: str) -> pd.DataFrame:
    empty = pd.DataFrame(columns=["Rk", "Squad"])
    seasons = (get_json(fetcher, f"/unique-tournament/{tournament_id}/seasons") or {}).get("seasons", [])
    sid = next((s["id"] for s in seasons if s.get("year") == season_year(club_season)), None)
    if sid is None:
        log.warning("SofaScore: no season %s for tournament %s", club_season, tournament_id)
        return empty
    return parse_standings(get_json(fetcher, f"/unique-tournament/{tournament_id}/season/{sid}/standings/total"))


def parse_standings(data: dict | None) -> pd.DataFrame:
    tables = (data or {}).get("standings") or []
    if not tables:
        return pd.DataFrame(columns=["Rk", "Squad"])
    rows = [(r["position"], r["team"]["name"]) for r in tables[0].get("rows", [])]
    return pd.DataFrame(rows, columns=["Rk", "Squad"]).astype({"Rk": int})
