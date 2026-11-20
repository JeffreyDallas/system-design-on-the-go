from __future__ import annotations

import shutil
import subprocess

import pytest

from podcast_pipeline import tts


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg unavailable")
def test_tts_segment_caching_and_mp3_assembly(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "ROOT", tmp_path)
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
