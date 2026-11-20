---
name: publish-episode
description: Upload approved audio and build the static episode page and RSS feed.
---

# Publish episode

Read `AGENTS.md` first. Publishing requires an approved script, matching rendered audio, and a public HTTPS R2 URL:

```bash
sd-podcast upload --slug <slug>
sd-podcast publish --slug <slug>
```

Verify the page has a native audio player, a transcript closed by default, escaped metadata, source and research links, the AI-voice disclosure, and a copyright contact/removal notice. Never put credentials or MP3s in Git. The RSS feed includes only episodes with public audio URLs.
