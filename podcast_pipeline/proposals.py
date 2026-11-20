"""Parse contributor episode proposals from GitHub Issue Forms."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .sources import MAX_SOURCES
from .util import secure_https_url

_HEADING = re.compile(r"^###\s+(.+?)\s*$", re.MULTILINE)
_URL = re.compile(r"https://[^\s<>()]+")
_SECTIONS = {"topic": "topic", "resources": "resources", "focus": "focus"}


def _sections(body: str) -> dict[str, str]:
    matches = list(_HEADING.finditer(body))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = _SECTIONS.get(match.group(1).strip().lower())
        if key:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            sections[key] = body[match.end():end].strip()
    return sections


def parse_proposal(body: str) -> dict[str, object]:
    """Validate and normalize the public fields in an Issue Form body."""
    sections = _sections(body)
    topic = sections.get("topic", "").strip()
    if not topic or topic.startswith("<!--"):
        raise ValueError("The proposal must include a topic")
    if len(topic) > 500:
        raise ValueError("The topic must be 500 characters or fewer")

    sources: list[str] = []
    for candidate in _URL.findall(sections.get("resources", "")):
        candidate = candidate.rstrip(".,;:")
        secure_https_url(candidate)
        if candidate not in sources:
            sources.append(candidate)
    if not 1 <= len(sources) <= MAX_SOURCES:
        raise ValueError(f"The proposal must include 1-{MAX_SOURCES} HTTPS resource links")

    focus = sections.get("focus", "").strip()
    if focus.startswith("<!--"):
        focus = ""
    if len(focus) > 1_000:
        raise ValueError("The focus must be 1,000 characters or fewer")
    problem = topic if not focus else f"{topic}\nAdditional focus: {focus}"
    return {"topic": topic, "focus": focus, "problem": problem, "sources": sources}


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse a GitHub episode proposal")
    parser.add_argument("--body-file", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(parse_proposal(args.body_file.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
