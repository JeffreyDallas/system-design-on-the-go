from __future__ import annotations

import shutil
import subprocess

import pytest

from podcast_pipeline import tts


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable")
def test_tts_segment_caching_and_mp3_assembly(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "ROOT", tmp_path)
    monkeypatch.setenv("TTS_PROVIDER", "elevenlabs")
    monkeypatch.setattr(tts, "env", lambda name: {
        "ELEVENLABS_VOICE_A": "voice-a", "ELEVENLABS_VOICE_B": "voice-b"
    }[name])
    calls = []
    def fake_synthesis(text, voice_id, output):
        calls.append((text, voice_id))
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", "0.15", "-codec:a", "libmp3lame", str(output)
        ], check=True, timeout=30)
    monkeypatch.setattr(tts, "_tts_segment", fake_synthesis)
    episode = {"turns": [
        {"speaker": "A", "text": "One approach is a shared Redis counter."},
        {"speaker": "B", "text": "Another approach is a local token bucket."},
    ]}
    folder = tmp_path / "episode"
    folder.mkdir()
    file, length = tts.render_audio(episode, folder)
    assert file.is_file() and file.stat().st_size > 1000
    assert length > 0.20
    assert [voice for _, voice in calls] == ["voice-a", "voice-b"]
    tts.render_audio(episode, folder)
    assert len(calls) == 2  # no paid synth calls on rerun


def test_duration_budget_is_hard():
    assert tts.validate_duration(20 * 60) == 20 * 60
    with pytest.raises(RuntimeError, match="maximum is 20 minutes"):
        tts.validate_duration(20 * 60 + 0.01)


def test_local_provider_uses_free_voice_path(monkeypatch, tmp_path):
    monkeypatch.setenv("TTS_PROVIDER", "local")
    monkeypatch.setenv("LOCAL_VOICE_A", "Samantha")
    monkeypatch.setenv("LOCAL_VOICE_B", "Alex")
    provider, voice_a, voice_b, synth, model = tts._provider_settings()
    assert provider == "local"
    assert (voice_a, voice_b, model) == ("Samantha", "Alex", "macos-say")
    assert synth is tts._local_tts_segment


def test_google_provider_uses_two_configured_voices(monkeypatch):
    monkeypatch.setenv("TTS_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_VOICE_A", "en-US-Neural2-F")
    monkeypatch.setenv("GOOGLE_VOICE_B", "en-US-Neural2-J")
    provider, voice_a, voice_b, synth, model = tts._provider_settings()
    assert provider == "google"
    assert (voice_a, voice_b, model) == (
        "en-US-Neural2-F", "en-US-Neural2-J", "en-US"
    )
    assert synth is tts._google_tts_segment


def test_google_tts_decodes_mp3_response(monkeypatch, tmp_path):
    import base64

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"audioContent": base64.b64encode(b"ID3fake-mp3").decode()}

    calls = {}

    def fake_post(url, **kwargs):
        calls.update(url=url, kwargs=kwargs)
        return Response()

    monkeypatch.setattr(tts, "env", lambda name: "google-key")
    monkeypatch.setattr(tts.httpx, "post", fake_post)
    output = tmp_path / "segment.mp3"
    tts._google_tts_segment("Hello", "en-US-Neural2-F", output)
    assert output.read_bytes() == b"ID3fake-mp3"
    assert calls["kwargs"]["json"]["voice"]["name"] == "en-US-Neural2-F"
