"""ElevenLabs dual-voice MP3 rendering, with cached segments and ffmpeg assembly."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from .util import ROOT, env, sha256, script_hash


def _tts_segment(text: str, voice_id: str, output: Path) -> None:
    key = env("ELEVENLABS_API_KEY")
    model = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    for attempt in range(4):
        with httpx.Client(timeout=120) as client:
            response = client.post(
                url,
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
                json={"text": text, "model_id": model},
            )
        if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
            time.sleep(min(2 ** attempt, 8))
            continue
        response.raise_for_status()
        if not response.content.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
            raise ValueError("Speech API returned unrecognized audio bytes")
        output.parent.mkdir(parents=True, exist_ok=True)
        part = output.with_suffix(".part")
        part.write_bytes(response.content)
        part.replace(output)
        return
    raise RuntimeError("Speech API exhausted retry attempts")


def render_audio(episode: dict, folder: Path) -> tuple[Path, float]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe must be installed and on PATH")
    a, b = env("ELEVENLABS_VOICE_A"), env("ELEVENLABS_VOICE_B")
    if a == b:
        raise ValueError("Choose distinct voice IDs for speaker A and B")
    voice_map = {"A": a, "B": b}
    model = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
    cache = ROOT / ".cache" / "tts"
    cache.mkdir(parents=True, exist_ok=True)
    files = []
    for index, turn in enumerate(episode["turns"]):
        voice = voice_map[turn["speaker"]]
        if len(turn["text"]) > 3500:
            raise ValueError(f"Turn {index} too long; split the script before rendering")
        fingerprint = sha256(json.dumps(["elevenlabs", model, voice, turn["text"]], ensure_ascii=False).encode())
        path = cache / f"{fingerprint}.mp3"
        if not path.exists() or path.stat().st_size < 1000:
            _tts_segment(turn["text"], voice, path)
        files.append(path)
    concat = folder / "_concat.txt"
    # All generated paths are under the project; quote for ffmpeg concat demuxer.
    concat.write_text("".join("file '" + str(f).replace("'", "'\\''") + "'\n" for f in files), encoding="utf-8")
    final = folder / "episode.mp3"
    temp = folder / "episode.tmp.mp3"
    try:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-codec:a", "libmp3lame", "-b:a", "128k", str(temp)],
            check=True, capture_output=True, text=True, timeout=1200,
        )
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(temp)],
            check=True, capture_output=True, text=True, timeout=60,
        )
        duration = float(result.stdout.strip())
        if duration <= 0 or temp.stat().st_size < 1000:
            raise RuntimeError("Invalid synthesized audio file")
        temp.replace(final)
        return final, duration
    finally:
        concat.unlink(missing_ok=True)
        temp.unlink(missing_ok=True)
