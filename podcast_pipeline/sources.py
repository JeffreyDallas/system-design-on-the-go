"""Extract text from trusted files or public HTTPS pages.

Not intended as a general public URL-fetching service. DNS checks are best effort;
production multi-tenant deployment should fetch through a hardened proxy.
"""
from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .util import ROOT

MAX_BYTES = 2_000_000
MAX_TEXT_CHARS = 16_000
MAX_SOURCES = 8


def validate_remote_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Sources must be public HTTPS URLs without credentials")
    if parsed.port not in (None, 443):
        raise ValueError("Only HTTPS port 443 is allowed")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("Source hostname did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Sources cannot resolve to private or reserved addresses")


def fetch_url(url: str) -> tuple[str, str]:
    with httpx.Client(timeout=25, follow_redirects=False, trust_env=False, headers={"User-Agent": "SystemDesignOnTheGo/0.1 (+source reader)"}) as client:
        for _ in range(5):
            validate_remote_url(url)
            with client.stream("GET", url) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Redirect has no Location header")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if not any(t in content_type for t in ("text/html", "text/plain", "application/xhtml+xml")):
                    raise ValueError(f"Unsupported source content-type: {content_type}")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise ValueError("Source exceeds 2 MB extraction cap")
                text = bytes(body).decode(response.encoding or "utf-8", errors="replace")
                if "html" not in content_type:
                    return url, text[:MAX_TEXT_CHARS]
                soup = BeautifulSoup(text, "html.parser")
                title = soup.title.get_text(" ", strip=True) if soup.title else url
                for tag in soup.select("script,style,nav,footer,header,aside,noscript,form"):
                    tag.decompose()
                element = soup.select_one("article") or soup.select_one("main") or soup.body or soup
                cleaned = element.get_text(" ", strip=True)
                return title, cleaned[:MAX_TEXT_CHARS]
        raise ValueError("Too many source redirects")


def collect_sources(inputs: list[str]) -> list[dict]:
    if not inputs or len(inputs) > MAX_SOURCES:
        raise ValueError(f"Provide 1-{MAX_SOURCES} sources (local .md/.txt files or HTTPS URLs)")
    sources = []
    for index, entry in enumerate(inputs, start=1):
        if entry.startswith("https://"):
            title, content = fetch_url(entry)
            sources.append({"id": f"S{index}", "title": title[:160], "url": entry, "text": content})
        else:
            path = Path(entry).expanduser().resolve()
            if path.suffix.lower() not in (".txt", ".md"):
                raise ValueError("Local source files must be .txt or .md")
            if not path.is_file() or path.stat().st_size > MAX_BYTES:
                raise ValueError(f"Missing or oversized source: {entry}")
            sources.append({"id": f"S{index}", "title": path.stem, "url": "", "text": path.read_text(encoding="utf-8")[:MAX_TEXT_CHARS]})
        if len(sources[-1]["text"]) < 80:
            raise ValueError(f"Too little readable content in source {entry}")
    return sources
