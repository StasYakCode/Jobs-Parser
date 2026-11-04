"""HTTP-клиент для публичных guest-эндпоинтов LinkedIn (без авторизации)."""
import logging
import random
import time

import requests
from django.conf import settings

log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]


class FetchError(Exception):
    """Любая ошибка загрузки."""


class NotFound(FetchError):
    """HTTP 404 — страница удалена."""


class RateLimited(FetchError):
    """429 / 999 / блокировка — нужно притормозить."""


class AuthWall(FetchError):
    """LinkedIn перенаправил на страницу логина."""


class LinkedInClient:
    def __init__(self):
        self.session = requests.Session()
        self._rotate_identity()

    def _rotate_identity(self):
        self.session.headers.clear()
        self.session.headers.update({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.session.cookies.clear()
        if settings.PROXY_URL:
            self.session.proxies.update({"http": settings.PROXY_URL, "https": settings.PROXY_URL})

    @staticmethod
    def _backoff(attempt):
        time.sleep(min(60, 2 ** attempt + random.uniform(0, 2)))

    def get(self, url, params=None):
        last_error = None
        for attempt in range(1, settings.HTTP_RETRIES + 1):
            time.sleep(random.uniform(settings.REQUEST_DELAY_MIN, settings.REQUEST_DELAY_MAX))
            try:
                resp = self.session.get(url, params=params, timeout=settings.HTTP_TIMEOUT)
            except requests.RequestException as exc:
                last_error = FetchError(f"network error: {exc}")
                log.warning("network error (attempt %s): %s", attempt, exc)
                self._backoff(attempt)
                continue

            code = resp.status_code
            if code == 200:
                if "authwall" in resp.url or "/login" in resp.url or "/uas/login" in resp.url:
                    raise AuthWall(f"redirected to login: {resp.url}")
                return resp.text
            if code == 404:
                raise NotFound(url)
            if code in (429, 999):
                last_error = RateLimited(f"HTTP {code}")
                log.warning("rate limited (HTTP %s), attempt %s", code, attempt)
                self._rotate_identity()
                self._backoff(attempt + 1)
                continue
            if code >= 500:
                last_error = FetchError(f"HTTP {code}")
                self._backoff(attempt)
                continue
            raise FetchError(f"HTTP {code} for {url}")
        raise last_error or FetchError("unknown error")
