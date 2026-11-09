"""HTTP GET with an on-disk cache and a fixed delay between requests."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "Mozilla/5.0 (compatible; ballon-dor-analysis/1.0; "
                  "+https://github.com/scheremetlenaa/ballon-dor-2026-analysis)",
}

NETWORK_ERRORS: tuple[type[Exception], ...] = (requests.RequestException,)
try:
    from playwright.sync_api import Error as PlaywrightError
    NETWORK_ERRORS += (PlaywrightError,)
except ImportError:
    pass


class NotFound(Exception):
    pass


class Blocked(Exception):
    """The site answered 403."""


def make_session(client: str = "requests", browser_profile: str | Path = "data/raw/browser-profile",
                 browser_options: dict | None = None):
    """client: 'requests' or 'browser' (a Chrome session, etl/browser.py)."""
    if client == "browser":
        from .browser import BrowserSession
        return BrowserSession(browser_profile, **(browser_options or {}))
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


class Fetcher:
    """GETs each URL once and keeps the answer in `cache_dir`; waits `delay` seconds between live requests.

    offline=True reads the cache only.
    """

    def __init__(self, cache_dir: str | Path, delay: float = 1.0, offline: bool = False,
                 session=None, client: str = "requests", browser_profile: str | Path = "data/raw/browser-profile",
                 browser_options: dict | None = None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.offline = offline
        self._session = session
        self._client = client
        self._browser_profile = browser_profile
        self._browser_options = browser_options
        self._last_request = 0.0

    @property
    def session(self):
        if self._session is None:          # created on the first live request
            self._session = make_session(self._client, self._browser_profile, self._browser_options)
        return self._session

    def close(self) -> None:
        if self._session is not None and hasattr(self._session, "close"):
            self._session.close()

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha1(url.encode()).hexdigest()
        return self.cache_dir / f"{key}.html", self.cache_dir / f"{key}.json"

    def get(self, url: str, headers: dict | None = None, refresh: bool = False) -> tuple[str, str]:
        """Returns (final_url, body). Raises NotFound for 404 (also cached) and Blocked for 403.

        refresh=True ignores the cached copy.
        """
        html_path, meta_path = self._paths(url)
        if meta_path.exists() and not (refresh and not self.offline):
            meta = json.loads(meta_path.read_text())
            if meta.get("status") == 404:
                raise NotFound(url)
            return meta["final_url"], html_path.read_text(encoding="utf-8")
        if self.offline:
            raise NotFound(f"not in cache (offline mode): {url}")

        for attempt in range(4):
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            log.info("GET %s", url)
            try:
                resp = self.session.get(url, timeout=30, headers=headers)
            except NETWORK_ERRORS as exc:
                log.warning("network error (%s), retrying", exc)
                time.sleep(2 ** (attempt + 1))
                continue
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                log.warning("429 Too Many Requests, sleeping %ss", retry_after)
                time.sleep(retry_after)
                continue
            if resp.status_code == 403:
                raise Blocked(url)
            if resp.status_code == 404:
                meta_path.write_text(json.dumps({"status": 404, "final_url": str(resp.url)}))
                raise NotFound(url)
            resp.raise_for_status()
            text = resp.content.decode("utf-8", errors="replace")
            html_path.write_text(text, encoding="utf-8")
            meta_path.write_text(json.dumps({"status": resp.status_code, "final_url": str(resp.url)}))
            return str(resp.url), text
        raise RuntimeError(f"giving up on {url}")
