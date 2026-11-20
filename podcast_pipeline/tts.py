"""Dual-voice MP3 rendering with cached segments and ffmpeg assembly."""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from .util import MAX_EPISODE_SECONDS, ROOT, env, sha256, script_hash


def validate_duration(seconds: float) -> float:
    if seconds <= 0:
        raise RuntimeError("Invalid synthesized audio duration")
    if seconds > MAX_EPISODE_SECONDS:
        raise RuntimeError(
            f"Synthesized episode is {seconds / 60:.1f} minutes; maximum is "
            f"{MAX_EPISODE_SECONDS / 60:.0f} minutes. Shorten the script and rerun."
        )
    return seconds


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


def _local_tts_segment(text: str, voice_id: str, output: Path) -> None:
    """Use macOS's built-in voices for free local pipeline testing."""
    if not shutil.which("say"):
        raise RuntimeError("TTS_PROVIDER=local requires macOS 'say' on PATH")
    output.parent.mkdir(parents=True, exist_ok=True)
    aiff = output.with_suffix(".aiff")
    aiff_part = aiff.with_suffix(".aiff.part")
    mp3_part = output.with_suffix(".part")
    try:
        subprocess.run(
            ["say", "-v", voice_id, "-o", str(aiff_part), text],
            check=True, capture_output=True, text=True, timeout=300,
        )
        aiff_part.replace(aiff)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(aiff), "-codec:a", "libmp3lame", "-b:a", "128k",
             "-f", "mp3", str(mp3_part)],
            check=True, capture_output=True, text=True, timeout=300,
        )
        mp3_part.replace(output)
    finally:
        aiff_part.unlink(missing_ok=True)
        aiff.unlink(missing_ok=True)
        mp3_part.unlink(missing_ok=True)


def _google_tts_segment(text: str, voice_id: str, output: Path) -> None:
    """Use Google Cloud Text-to-Speech with an API key and a named voice."""
    key = env("GOOGLE_CLOUD_AUDIO_API_KEY")
    language_code = os.getenv("GOOGLE_TTS_LANGUAGE_CODE", "en-US").strip()
    response = httpx.post(
        "https://texttospeech.googleapis.com/v1/text:synthesize",
        params={"key": key},
        json={
            "input": {"text": text},
            "voice": {"languageCode": language_code, "name": voice_id},
            "audioConfig": {"audioEncoding": "MP3"},
        },
        timeout=120,
    )
    response.raise_for_status()
    try:
        audio = base64.b64decode(response.json()["audioContent"], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Google TTS returned an invalid audio response") from exc
    if not audio.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
        raise ValueError("Google TTS returned unrecognized audio bytes")
    output.parent.mkdir(parents=True, exist_ok=True)
    part = output.with_suffix(".part")
    part.write_bytes(audio)
    part.replace(output)


def _provider_settings() -> tuple[str, str, str, object, str]:
    provider = os.getenv("TTS_PROVIDER", "elevenlabs").strip().lower()
    if provider == "local":
        a = os.getenv("LOCAL_VOICE_A", "Samantha").strip()
        b = os.getenv("LOCAL_VOICE_B", "Alex").strip()
        return provider, a, b, _local_tts_segment, "macos-say"
    if provider == "google":
        a = os.getenv("GOOGLE_VOICE_A", "en-US-Neural2-F").strip()
        b = os.getenv("GOOGLE_VOICE_B", "en-US-Neural2-J").strip()
        return provider, a, b, _google_tts_segment, os.getenv("GOOGLE_TTS_LANGUAGE_CODE", "en-US")
    if provider == "elevenlabs":
        a, b = env("ELEVENLABS_VOICE_A"), env("ELEVENLABS_VOICE_B")
        return provider, a, b, _tts_segment, os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")
    raise ValueError("TTS_PROVIDER must be 'elevenlabs', 'google', or 'local'")


def render_audio(episode: dict, folder: Path) -> tuple[Path, float]:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe must be installed and on PATH")
    provider, a, b, synth, model = _provider_settings()
    if a == b:
        raise ValueError("Choose distinct voice IDs for speaker A and B")
    voice_map = {"A": a, "B": b}
    cache = ROOT / ".cache" / "tts"
    cache.mkdir(parents=True, exist_ok=True)
    files = []
    for index, turn in enumerate(episode["turns"]):
        voice = voice_map[turn["speaker"]]
        if len(turn["text"]) > 3500:
            raise ValueError(f"Turn {index} too long; split the script before rendering")
        fingerprint = sha256(json.dumps([provider, model, voice, turn["text"]], ensure_ascii=False).encode())
        path = cache / f"{fingerprint}.mp3"
        if not path.exists() or path.stat().st_size < 1000:
            synth(turn["text"], voice, path)
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
        validate_duration(duration)
        if temp.stat().st_size < 1000:
            raise RuntimeError("Invalid synthesized audio file")
        temp.replace(final)
        return final, duration
    finally:
        concat.unlink(missing_ok=True)
        temp.unlink(missing_ok=True)
