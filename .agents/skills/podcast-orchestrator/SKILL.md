---
name: podcast-orchestrator
description: Run the resumable source-to-publication podcast workflow with review controls.
---

# Podcast orchestrator

Read `AGENTS.md` first. For a reviewable run, create the draft and stop:

```bash
sd-podcast run --slug <slug> --problem '<problem>' --source <url-or-file>
```

Inspect and edit `episodes/<slug>/episode.json`, then resume explicitly with `--approve`. Only use `--approve` unattended when the protected workflow or an authorized human has accepted the script. Existing approved scripts, cached TTS turns, and unchanged uploaded audio must be reused to avoid duplicate cost.
