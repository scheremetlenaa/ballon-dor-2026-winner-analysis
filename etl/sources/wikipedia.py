"""Ballon d'Or voting results from English Wikipedia ("<year> Ballon d'Or" pages)."""
from __future__ import annotations

import logging
import re
from io import StringIO

import pandas as pd

from ..fetch import Fetcher, NotFound

log = logging.getLogger(__name__)

BASE = "https://en.wikipedia.org/wiki/"


def page_url(year: int) -> str:
    # 2010–2015: "FIFA Ballon d'Or" pages
    title = f"{year}_FIFA_Ballon_d%27Or" if 2010 <= year <= 2015 else f"{year}_Ballon_d%27Or"
    return BASE + title


def _flat(col) -> str:
    if isinstance(col, tuple):
        parts = [str(p) for p in col if not str(p).startswith("Unnamed")]
        col = parts[-1] if parts else ""
    return re.sub(r"\[.*?\]", "", str(col)).strip()


def _find(cols: list[str], pattern: str) -> str | None:
    for c in cols:
        if re.search(pattern, c, flags=re.I):
            return c
    return None


def _clean_name(name) -> str | None:
    if not isinstance(name, str):
        return None
    name = re.sub(r"\[.*?\]", "", name)        # footnotes
    name = re.sub(r"\(.*?\)", "", name)        # "(c)", "(GK)"
    name = re.sub(r"\s+", " ", name).strip(" *†‡")
    return name or None


def _to_int(value) -> int | None:
    m = re.search(r"\d+", str(value).replace(",", ""))
    return int(m.group()) if m else None


def _to_share(value) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", "."))
    return float(m.group()) / 100 if m else None


def parse_voting(html: str) -> pd.DataFrame:
    """The men's ranking table: Rank, PlayerName, Points, VoteSharePct.

    Takes the first table with a Player and a Points column, else the first with a percentage column.
    """
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        tables = []
    def has_points(t) -> bool:
        cols = [_flat(c) for c in t.columns]
        return bool(_find(cols, r"^player") and _find(cols, r"^points?$|^pts"))
    tables = sorted(tables, key=lambda t: not has_points(t))     # stable: page order otherwise
    for t in tables:
        t = t.copy()
        t.columns = [_flat(c) for c in t.columns]
        cols = list(t.columns)
        player = _find(cols, r"^player")
        points = _find(cols, r"^points?$|^pts")
        share = _find(cols, r"%|percent|share|votes")
        if not player or not (points or share) or len(t) < 5:
            continue
        rank = _find(cols, r"^(rank|pos|position|no\.?|#)$")
        out = pd.DataFrame({
            "PlayerName": t[player].map(_clean_name),
            "Rank": t[rank].map(_to_int) if rank else pd.Series(range(1, len(t) + 1)),
            "Points": t[points].map(_to_int) if points else None,
            "VoteSharePct": t[share].map(_to_share) if share and share != points else None,
        })
        out = out[out["PlayerName"].notna() & ~out["PlayerName"].str.fullmatch(r"(?i)player|total")]
        # tied ranks in merged cells: the last rank is carried down
        out["Rank"] = out["Rank"].ffill().astype("Int64")
        out["Points"] = pd.to_numeric(out["Points"], errors="coerce").astype("Int64")
        out["VoteSharePct"] = pd.to_numeric(out["VoteSharePct"], errors="coerce")
        return out.drop_duplicates("PlayerName").reset_index(drop=True)
    raise ValueError("no ranking table found")


def load_voting(fetcher: Fetcher, year: int, refresh: bool = False) -> pd.DataFrame | None:
    """Voting table of one award year; refresh=True ignores the cached page."""
    url = page_url(year)
    try:
        _, html = fetcher.get(url, refresh=refresh)
    except NotFound:
        log.warning("Wikipedia page not found for %s: %s", year, url)
        return None
    try:
        df = parse_voting(html)
    except ValueError:
        log.warning("no voting table on %s", url)
        return None
    df.insert(0, "BallonDorYear", year)
    log.info("%s: %d players in voting table", year, len(df))
    if df["Points"].isna().all() and df["VoteSharePct"].isna().all():
        log.warning("%s: the voting table has ranks but no points", year)
    return df
