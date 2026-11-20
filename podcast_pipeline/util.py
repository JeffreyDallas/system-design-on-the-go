from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
MAX_EPISODE_SECONDS = 20 * 60
MAX_SCRIPT_WORDS = 2_600
TRANSCRIPT_FORMAT = "conversation-v1"
load_dotenv(ROOT / ".env")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slug_check(slug: str) -> str:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or len(slug) > 70:
        raise ValueError("Slug must be lowercase hyphenated characters, max 70")
    return slug


def episode_dir(slug: str) -> Path:
    return ROOT / "episodes" / slug_check(slug)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value == "replace_me":
        raise RuntimeError(f"Missing {name}: configure .env (see .env.example)")
    return value


def env_or(name: str, default: str) -> str:
    """Read a stripped environment value, falling back when it is unset or empty."""
    return os.environ.get(name, "").strip() or default


def secure_https_url(url: str) -> str:
    p = urlsplit(url)
    if (p.scheme != "https" or not p.hostname or p.username or p.password
            or p.port not in (None, 443)):
        raise ValueError("Public URLs must be HTTPS without credentials")
    return url


def script_hash(episode: dict) -> str:
    return sha256(json.dumps(episode["turns"], ensure_ascii=False, sort_keys=True).encode())


def retry_call(operation, *, attempts: int = 4, label: str = "operation",
               retry_if=None, initial_delay: float = 1.0, max_delay: float = 20.0):
    """Retry a transient operation with visible progress and bounded backoff."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # callers provide retry_if for non-transient errors
            last_error = exc
            transient = retry_if(exc) if retry_if else True
            if not transient or attempt == attempts:
                raise
            delay = min(initial_delay * (2 ** (attempt - 1)), max_delay)
            print(f"{label} failed ({type(exc).__name__}); retry {attempt}/{attempts - 1} in {delay:.0f}s...",
                  file=sys.stderr, flush=True)
            time.sleep(delay)
    raise last_error  # pragma: no cover
