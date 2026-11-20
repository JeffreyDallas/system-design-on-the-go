---
name: dialogue-to-audio
description: Render an approved two-speaker script into cached MP3 audio and check its output.
---

# Dialogue to audio

Read `AGENTS.md` first. Only render an approved, current `episode.json`:

```bash
sd-podcast render --slug <slug>
```

The renderer maps A and B to distinct configured voices, caches completed turns, joins them with ffmpeg, and validates duration with ffprobe. Never commit `episode.mp3` or local TTS cache files. Listen to the resulting audio when human review is available.
