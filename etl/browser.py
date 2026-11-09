"""Session with the `get(url, timeout, headers)` interface of requests, backed by a Chrome window (Playwright).

Chrome is started with a remote-debugging port and a persistent profile; Playwright connects to it over CDP.
JSON URLs are requested with fetch() from a page of the same site; other URLs are opened in the page.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

FETCH_JS = """async ([url, ms]) => {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), ms);
    try {
        const r = await fetch(url, {credentials: "include", headers: {"Accept": "application/json"},
                                    signal: ctl.signal});
        return {status: r.status, body: await r.text(), url: r.url};
    } finally {
        clearTimeout(timer);
    }
}"""


@dataclass
class BrowserResponse:
    status_code: int
    content: bytes
    url: str
    headers: dict = field(default_factory=dict)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code} for {self.url}")


def find_chrome() -> str | None:
    """Path to an installed Google Chrome or Chromium, or None."""
    candidates = []
    if sys.platform == "win32":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return next((str(p) for p in candidates if p.exists()), None)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_devtools(port: int, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                json.load(r)
                return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError("Chrome did not open its debugging port")


class BrowserSession:
    def __init__(self, profile_dir: str | Path, headless: bool = False, chrome_path: str | None = None):
        from playwright.sync_api import sync_playwright
        self.headers: dict = {}
        self._proc = None
        profile_dir = Path(profile_dir).resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        chrome_path = chrome_path or find_chrome()
        if not chrome_path:
            raise SystemExit("Google Chrome not found; set chrome_path in etl/config.yaml")
        self._pw = sync_playwright().start()
        try:
            self._ctx = self._connect(chrome_path, profile_dir, headless)
        except BaseException:
            self.close()
            raise
        self._page = self._ctx.new_page()

    def _connect(self, chrome_path, profile_dir, headless):
        port = _free_port()
        args = [chrome_path, f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}",
                "--no-first-run", "--no-default-browser-check"]
        if headless:
            args.append("--headless=new")
        self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _wait_for_devtools(port)
        self._browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        return self._browser.contexts[0]

    def get(self, url: str, timeout: float = 30, headers: dict | None = None) -> BrowserResponse:
        if self._page.is_closed():
            self._page = self._ctx.new_page()
        if "json" in (headers or {}).get("Accept", ""):
            return self._fetch_json(url, timeout)
        resp = self._page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        status = resp.status if resp is not None else 200
        for _ in range(5):           # content() raises while a redirect is in progress
            try:
                html = self._page.content()
                break
            except Exception:
                self._page.wait_for_timeout(1000)
        else:
            html = self._page.content()
        return BrowserResponse(status, html.encode("utf-8"), self._page.url)

    def _fetch_json(self, url: str, timeout: float) -> BrowserResponse:
        """fetch() from the site's home page; after a 403 the home page is reloaded and the request repeated once."""
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        for attempt in range(2):
            if attempt or not self._page.url.startswith(origin):
                self.get(origin + "/", timeout)
            r = self._page.evaluate(FETCH_JS, [url, int(timeout * 1000)])
            if r["status"] != 403:
                break
        return BrowserResponse(r["status"], r["body"].encode("utf-8"), r["url"] or url)

    def close(self) -> None:
        try:
            if getattr(self, "_browser", None) is not None:
                self._browser.close()
        except Exception:
            pass
        finally:
            if self._proc is not None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._pw.stop()
