from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from podcast_pipeline.util import script_hash, slug_check
from podcast_pipeline.writer import validate_script
from podcast_pipeline.website import build_site, episode_html, feed_xml, index_html


def valid_episode():
    return {
        "slug":"rate-limiter", "title":"Rate Limiter <script>alert(1)</script>",
        "description":"Two colleagues discuss constraints.",
        "problem":"Rate limit a distributed API.",
        "created_at":"2026-11-20T12:00:00+00:00", "published_at":"2026-11-20T12:00:00+00:00",
        "turns":[{"speaker":"A" if i%2==0 else "B", "text":"Let's evaluate the design and operational trade-offs carefully."} for i in range(8)],
        "references":[{"id":"S1","title":"Reference <img src=x>","url":"https://example.com/page"}],
        "audio_url":"https://audio.example.com/episodes/rate-limiter/abc.mp3", "audio_bytes":1234,
    }


def test_slug_rejects_path_traversal():
    assert slug_check("rate-limiter") == "rate-limiter"
    for bad in ["../secrets", "A", "x/y", "x--y", "", "with spaces"]:
        with pytest.raises(ValueError):
            slug_check(bad)


def test_script_validation_and_hash_change():
    ep = valid_episode()
    validate_script(ep)
    h1 = script_hash(ep)
    ep["turns"][0]["text"] += " Changed."
    assert script_hash(ep) != h1
    ep["turns"][0]["speaker"] = "interviewer"
    with pytest.raises(ValueError):
        validate_script(ep)


def test_transcript_hidden_and_escaped():
    html = episode_html(valid_episode())
    assert "<details>" in html and "<details open" not in html
    assert "<audio controls" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x&gt;" in html
    assert "Engineer A" in html and "Engineer B" in html


def test_audio_url_scheme_blocked():
    ep = valid_episode()
    ep["audio_url"] = "javascript:alert(1)"
    html = episode_html(ep)
    assert "<audio controls" not in html
    assert "Audio is not published" in html


def test_feed_only_includes_episodes_with_audio():
    ep = valid_episode()
    no_audio = {**ep, "slug":"no-audio", "audio_url":""}
    cfg = {"name":"Demo", "site_url":"https://example.github.io/project/", "description":"Test podcast"}
    data = feed_xml([ep, no_audio], cfg).decode()
    assert data.count("<item>") == 1
    assert 'type="audio/mpeg"' in data
    assert "/project/episodes/rate-limiter/" in data
    assert "no-audio" not in data


def test_index_escapes_html():
    ep = valid_episode()
    html = index_html([ep], {"description":"sample", "tagline":"Sample"})
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_build_site_removes_stale_generated_episode(monkeypatch, tmp_path):
    monkeypatch.setattr("podcast_pipeline.website.ROOT", tmp_path)
    (tmp_path / "episodes" / "current").mkdir(parents=True)
    (tmp_path / "episodes" / "current" / "episode.json").write_text(
        json.dumps({**valid_episode(), "slug": "current"}), encoding="utf-8"
    )
    stale = tmp_path / "docs" / "episodes" / "stale"
    stale.mkdir(parents=True)
    (stale / "index.html").write_text("old", encoding="utf-8")
    (tmp_path / "site.json").write_text(json.dumps({
        "name": "Demo", "site_url": "https://example.com/", "description": "Demo"
    }), encoding="utf-8")

    count, _ = build_site()

    assert count == 1
    assert not stale.exists()
    assert (tmp_path / "docs" / "episodes" / "current" / "index.html").exists()
