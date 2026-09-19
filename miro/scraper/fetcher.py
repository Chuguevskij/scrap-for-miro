"""Получение HTML без привязки скрейпера к конкретному HTTP-клиенту."""

import http.cookiejar
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from typing import Protocol
import re

from .models import Page


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class PageFetcher(Protocol):
    def fetch(self, url: str) -> Page:
        """Получить страницу и вернуть URL после редиректов."""


class HttpPageFetcher:
    """HTTP-загрузчик с cookies, редиректами и повтором после HTTP 429."""

    def __init__(self, timeout: int = 40, retries: int = 5, sleep=time.sleep):
        self.timeout = timeout
        self.retries = retries
        self.sleep = sleep
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.opener.addheaders = [
            ("User-Agent", USER_AGENT),
            ("Accept", "text/html,application/xhtml+xml"),
            ("Accept-Language", "cs,en;q=0.9,ru;q=0.8"),
        ]

    def fetch(self, url: str) -> Page:
        html, final_url = self._get(url)

        # Некоторые CDN отдают короткую HTML-заглушку с meta refresh.
        for _ in range(2):
            match = re.search(r"URL=['\"]([^'\"]+)['\"]", html, re.I)
            if not match or len(html) > 20_000:
                break
            next_url = urllib.parse.urljoin(final_url, unescape(match.group(1)))
            html, final_url = self._get(next_url)

        if not html.strip():
            raise RuntimeError("страница получена пустой")
        return Page(url=url, final_url=final_url, html=html)

    def _get(self, url: str) -> tuple[str, str]:
        for attempt in range(1, self.retries + 1):
            try:
                with self.opener.open(url, timeout=self.timeout) as response:
                    charset = response.headers.get_content_charset() or "utf-8"
                    return response.read().decode(charset, "replace"), response.geturl()
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == self.retries:
                    raise
                pause = float(exc.headers.get("Retry-After") or 15 * attempt)
                self.sleep(pause)


class LocalFileFetcher:
    """Загрузчик HTML-файлов для offline-запуска и тестов."""

    def fetch(self, url: str) -> Page:
        path = url[7:] if url.startswith("file://") else url
        with open(path, encoding="utf-8", errors="replace") as stream:
            html = stream.read()
        absolute = "file://" + path
        return Page(url=url, final_url=absolute, html=html)
