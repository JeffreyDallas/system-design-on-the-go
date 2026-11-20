from __future__ import annotations

import json

import pytest

from podcast_pipeline.util import MAX_SCRIPT_WORDS, env_or, script_hash, slug_check
from podcast_pipeline.sources import _split_markdown
from podcast_pipeline import writer
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


def test_env_or_ignores_empty_values(monkeypatch):
    monkeypatch.setenv("SCRIPT_MODEL", "")
    assert env_or("SCRIPT_MODEL", "gpt-4.1-mini") == "gpt-4.1-mini"
    monkeypatch.setenv("SCRIPT_MODEL", "  gpt-5.4-mini  ")
    assert env_or("SCRIPT_MODEL", "gpt-4.1-mini") == "gpt-5.4-mini"


def test_script_validation_and_hash_change():
    ep = valid_episode()
    validate_script(ep)
    h1 = script_hash(ep)
    ep["turns"][0]["text"] += " Changed."
    assert script_hash(ep) != h1
    ep["turns"][0]["speaker"] = "interviewer"
    with pytest.raises(ValueError):
        validate_script(ep)


def test_source_code_is_retained_as_non_spoken_artifact():
    narrative, artifacts = _split_markdown(
        "The service uses an atomic counter.\n\n```bash\nredis-cli INCR quota\n```\n"
    )
    assert "atomic counter" in narrative
    assert "redis-cli INCR quota" not in narrative
    assert "redis-cli INCR quota" in artifacts


def test_script_rejects_shell_snippets():
    script = {"title": "Design", "description": "Discussion", "turns": [
        {"speaker": "A" if i % 2 == 0 else "B", "text":
         ("We should discuss the design trade-offs and failure behavior carefully."
          if i != 0 else "We should test it in a shell.\n$ redis-cli INCR quota")}
        for i in range(8)
    ]}
    with pytest.raises(ValueError, match="shell snippets"):
        validate_script(script)


def test_script_rejects_oversized_dialogue():
    text = "architecture tradeoff " * (MAX_SCRIPT_WORDS // 2 + 1)
    script = {"title": "Design", "description": "Discussion", "turns": [
        {"speaker": "A" if i % 2 == 0 else "B", "text": text[:3500]}
        for i in range(12)
    ]}
    with pytest.raises(ValueError, match="spoken words"):
        validate_script(script)


def test_incomplete_sources_keep_only_cited_research_links(monkeypatch):
    class Annotation:
        def __init__(self, url, title):
            self.type = "url_citation"
            self.url = url
            self.title = title

    class Content:
        def __init__(self, annotations):
            self.annotations = annotations

    class Item:
        def __init__(self, content):
            self.content = content

    class Response:
        output = [Item([Content([
            Annotation("https://docs.example.com/design", "Design docs"),
            Annotation("http://unsafe.example.com", "Not HTTPS"),
        ])])]

    def fake_call(system_prompt, user_prompt, *, web_search=False):
        assert web_search
        return ({"research_summary": "Added the missing failure-handling context.",
                 "sources": [{"source_id": "R1", "title": "Design docs",
                              "url": "https://docs.example.com/design",
                              "why_relevant": "Explains recovery."}]}, Response())

    monkeypatch.setattr(writer, "_call_json", fake_call)
    research, refs = writer._research_if_needed(
        "Design a resilient service",
        "The source describes only the happy path.",
        {"source_assessment": {"sufficient": False,
                                "research_questions": ["How does recovery work?"]}},
    )

    assert research["sources"] == [{"id": "R1", "title": "Design docs",
                                     "url": "https://docs.example.com/design"}]
    assert refs == research["sources"]


def test_research_evidence_follows_renumbered_citations(monkeypatch):
    class Annotation:
        def __init__(self, url, title):
            self.type = "url_citation"
            self.url = url
            self.title = title

    class Content:
        def __init__(self, annotations):
            self.annotations = annotations

    class Item:
        def __init__(self, content):
            self.content = content

    class Response:
        output = [Item([Content([
            Annotation("https://b.example.com/doc", "B docs"),
            Annotation("https://a.example.com/doc", "A docs"),
        ])])]

    def fake_call(system_prompt, user_prompt, *, web_search=False):
        return ({
            "research_summary": "Two cited sources plus one uncited claim.",
            "evidence": [
                {"claim": "Claim from A.", "source_id": "R1"},
                {"claim": "Claim from B.", "source_id": "R2"},
                {"claim": "Claim from an uncited source.", "source_id": "R3"},
            ],
            "sources": [
                {"source_id": "R1", "title": "A docs", "url": "https://a.example.com/doc"},
                {"source_id": "R2", "title": "B docs", "url": "https://b.example.com/doc"},
                {"source_id": "R3", "title": "Uncited", "url": "https://c.example.com/doc"},
            ],
        }, Response())

    monkeypatch.setattr(writer, "_call_json", fake_call)
    brief = {"source_assessment": {"sufficient": False}, "uncertainties": ["Existing uncertainty"]}
    research, refs = writer._research_if_needed("Design a resilient service", "sources", brief)

    ids = {ref["title"]: ref["id"] for ref in refs}
    assert ids == {"B docs": "R1", "A docs": "R2"}
    assert research["evidence"] == [
        {"claim": "Claim from A.", "source_id": "R2"},
        {"claim": "Claim from B.", "source_id": "R1"},
    ]
    assert brief["uncertainties"][0] == "Existing uncertainty"
    assert any("Claim from an uncited source." in note for note in brief["uncertainties"])


def test_transcript_hidden_and_escaped():
    html = episode_html(valid_episode())
    assert "<details>" in html and "<details open" not in html
    assert "<audio controls" in html
    assert 'data-seek="-15"' in html and 'data-seek="15"' in html
    assert "data-playback-speed" in html and "playbackRate" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=x&gt;" in html
    assert "Engineer A" in html and "Engineer B" in html
    assert "Copyright concern?" in html
    assert "Contact us to request review or removal" in html


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
