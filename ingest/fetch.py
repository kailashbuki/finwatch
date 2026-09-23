"""Cached HTTP fetching with per-host quirk handling.

Every upstream in this project is a public, unauthenticated endpoint, but several
require a specific ``Accept`` header or they silently return the wrong format.
Those quirks are verified facts, not guesses -- see ``HOST_ACCEPT``.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"

SDMX_JSON = "application/vnd.sdmx.data+json"

#: Per-host ``Accept`` defaults. Both of these return SDMX-ML XML (BIS) or an
#: outright HTTP 406 (Bundesbank) if the header is missing or imprecise.
HOST_ACCEPT: dict[str, str] = {
    "stats.bis.org": SDMX_JSON,
    "api.statistiken.bundesbank.de": f"{SDMX_JSON};version=1.0.0",
}

#: Hosts that block datacenter/cloud IPs with an HTTP 403 WAF response. Anything
#: depending on these works locally and fails in CI, so they are refused outright.
BLOCKED_HOSTS = frozenset({"www.imf.org"})

DEFAULT_TIMEOUT = 120.0
MAX_ATTEMPTS = 4


class UpstreamError(RuntimeError):
    """A fetch failed after exhausting retries."""


def _cache_path(url: str, suffix: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:20]
    host = urlsplit(url).netloc.replace(":", "_")
    return CACHE_DIR / host / f"{digest}{suffix}"


def fetch(
    url: str,
    *,
    accept: str | None = None,
    suffix: str = ".dat",
    use_cache: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> bytes:
    """GET ``url``, returning the body and caching it on disk.

    The cache is keyed on the full URL and is intended for development and for
    re-running a build without re-hitting upstreams; CI runs with a cold cache.
    """
    host = urlsplit(url).netloc
    if host in BLOCKED_HOSTS:
        raise UpstreamError(
            f"{host} blocks cloud IPs with HTTP 403; use api.imf.org / data.imf.org instead"
        )

    path = _cache_path(url, suffix)
    if use_cache and path.exists():
        log.debug("cache hit %s", url)
        return path.read_bytes()

    headers = {"Accept": accept or HOST_ACCEPT.get(host, "*/*")}
    last: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = httpx.get(
                url, headers=headers, timeout=timeout, follow_redirects=True
            )
            response.raise_for_status()
        except (httpx.HTTPError, httpx.StreamError) as exc:
            last = exc
            if attempt == MAX_ATTEMPTS:
                break
            backoff = 2.0**attempt
            log.warning(
                "fetch %s failed (attempt %d): %s; retrying in %.0fs", url, attempt, exc, backoff
            )
            time.sleep(backoff)
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        log.info("fetched %s (%d bytes)", url, len(response.content))
        return response.content

    raise UpstreamError(f"failed to fetch {url}: {last}") from last
