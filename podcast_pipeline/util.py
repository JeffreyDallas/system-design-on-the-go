from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
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


def secure_https_url(url: str) -> str:
    p = urlsplit(url)
    if p.scheme != "https" or not p.hostname or p.username or p.password:
        raise ValueError("Public URLs must be HTTPS without credentials")
    return url


def script_hash(episode: dict) -> str:
    return sha256(json.dumps(episode["turns"], ensure_ascii=False, sort_keys=True).encode())
