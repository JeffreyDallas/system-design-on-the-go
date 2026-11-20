---
name: dialogue-to-audio
description: Render an approved two-speaker script into cached MP3 audio and check its output.
---

# Dialogue to audio

Read `AGENTS.md` first. Only render an approved, current `episode.json`:

```bash
sd-podcast render --slug <slug>
```

The renderer maps A and B to distinct configured voices, caches completed turns, joins them with ffmpeg, and validates duration with ffprobe. Use `TTS_PROVIDER=local` with two macOS `say` voices for free local pipeline testing; use `TTS_PROVIDER=elevenlabs` for production-quality hosted audio. The final MP3 must not exceed 20 minutes; an over-limit render fails before replacing the episode file. The approved transcript should contain conversational explanations rather than source code, shell commands, flags, or line-by-line implementation instructions. Never commit `episode.mp3` or local TTS cache files. Listen to the resulting audio when human review is available.

Transient hosted-TTS failures are retried with bounded backoff and completed segments remain cached. Every CLI failure must return a nonzero exit and state the corrective action; do not treat a blocked review checkpoint or missing configuration as success.
