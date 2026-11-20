# System Design on the Go 🎧

**Two engineers. One problem. Better architecture.**

An open-source, agent-friendly system that turns system-design sources and engineering problems into a **two-engineer collaborative podcast**—not an interview, not a narrated article. An AI design brief drives real discussion of constraints, alternatives, operational behavior, and trade-offs. The result is a hosted MP3, a dedicated GitHub Pages episode, a **collapsed-by-default transcript**, source references and RSS.

> **Status:** Working project with offline-tested site generation, CLI orchestration, ElevenLabs/Google/local TTS and Cloudflare R2 integration. The included episodes were produced end to end with live API calls and R2 uploads; reproducing that requires *your own credentials*, and GitHub Pages deployment requires your own repository.

## Table of contents

- [How it works](#how-it-works)
- [Contributor episode workflow](#contributor-episode-workflow)
- [Quick start](#quick-start)
- [Create an episode, with review](#create-an-episode-with-review)
- [AI services and audio choices](#ai-services-and-audio-choices)
- [Cloudflare R2 setup](#cloudflare-r2-setup)
- [GitHub Pages setup](#github-pages-setup)
- [Agent Skills](#agent-skills)
- [Safety, reliability and limitations](#safety-reliability-and-limitations)
- [Tests](#tests)
- [Project layout](#project-layout)

## How it works

```text
Public HTTPS articles / local text + engineering problem
      │
      ▼
Source extraction → design brief (source-grounded facts, assumptions, alternatives)
      │
      ▼
 Two peer engineers' original dialogue (OpenAI Responses API)
      │
      ▼
 [Review checkpoint: edit episode.json / approve]
      │
      ▼
 Speaker A / Speaker B TTS (ElevenLabs; cached per dialogue turn)
      │
      ▼
 ffmpeg single MP3 → Cloudflare R2 (content-addressed URL)
      │
      ▼
 GitHub Pages /episodes/<slug>/ + native HTML5 player + closed transcript
      │
      └── RSS podcast feed /feed.xml
```

## Contributor episode workflow

Contributors only need to submit an issue with:

- a system-design topic;
- one to eight public HTTPS resource links; and
- an optional focus, such as scale, failure modes, or trade-offs.

| Step | Owner or trigger | Result |
| --- | --- | --- |
| 1. Propose | Contributor opens an **Episode proposal** issue | Topic and resources are captured; no repository changes are required. |
| 2. Accept | Maintainer adds `episode/accepted` | `generate-episode-draft.yml` validates the issue, creates the design brief and draft `episode.json`, opens a draft PR, and comments the PR link on the issue. |
| 3. Review | Maintainer reviews the draft PR | The script is checked for technical accuracy, supported claims, and meaningful contributions from both engineers. |
| 4. Approve | Maintainer adds `episode/production-approved` and merges the PR | The reviewed episode is added to `main`. |
| 5. Produce | Merge triggers `produce-approved-episode.yml` | Cached TTS is rendered, audio is uploaded to R2, Pages/RSS are rebuilt, and publication metadata is committed. |

The production workflow checks out `main` after merge and only processes the episode changed by that PR. Contributors cannot trigger paid production because the approval label and merge are maintainer-controlled. Configure the `podcast-production` environment with required reviewers if an additional release approval is desired.

### Dry runs and configuration

- Run either workflow from **Actions** with `dry_run: true` (the default) to validate inputs and print the plan without model calls, TTS, R2 uploads, PR creation, or commits.
- `publish-episode.yml` remains a maintainer-only fallback for an already-reviewed episode and also defaults to dry run.
- Configure repository secrets for OpenAI, ElevenLabs or Google TTS, and Cloudflare R2. Configure variables for `TTS_PROVIDER`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL`, and optional model/voice settings.
- Ensure Actions can write repository contents, and configure branch protection as needed.

For local review, use `sd-podcast new` to create a draft, inspect and edit `episodes/<slug>/episode.json`, then explicitly run `sd-podcast run --slug <slug> --approve` only after accepting the script. Unchanged approved scripts and cached TTS segments are reused to avoid duplicate cost.

## Quick start

Requires **Python 3.11+** and `ffmpeg` + `ffprobe` (`brew install ffmpeg` on macOS; `sudo apt install ffmpeg` on Ubuntu).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
# Fill in your own keys (never commit .env)
```

The template is the hidden root file [.env.example](.env.example); use `ls -la` or enable hidden files in your editor if it is not visible.

Preview the generated site locally:

```bash
python -m http.server 8000 --directory docs
# Open http://localhost:8000/
```

## Create an episode, with review

```bash
sd-podcast run \
  --source 'https://redis.io/docs/latest/develop/use/patterns/' \
  --source 'examples/rate-limiter-notes.md'
```

The sources determine the episode title, engineering problem, and safe slug automatically. **This first invocation stops** after generating the design brief and `episode.json`. Open and edit the canonical `episode.json` if needed; check that both engineers contribute, no source facts are invented, and technical trade-offs hold up. The generated slug is printed by the command. Then:

```bash
sd-podcast run --slug distributed-rate-limiter --approve
```

That second command renders voice audio, uploads it to R2, records the public MP3 URL and rebuilds the Pages website. `--approve` is an explicit skip/confirmation of the review checkpoint. For an unattended one-command run, include `--approve` in the *first* command. You can also run the stages independently:

```bash
sd-podcast new        --source '...'
sd-podcast render     --slug ...
sd-podcast upload     --slug ...
sd-podcast publish    --slug ...
sd-podcast build-site
```

For an agent-style guided session, run:

```bash
sd-podcast interactive
```

The command asks only for the number of source resources, then collects each URL or local `.md`/`.txt` path as a numbered input. It uses one compact, low-output model pass over the resources to infer a concise episode title, engineering problem, and safe slug before starting the design brief and dialogue stages. By default it pauses at the human review checkpoint before paid audio, upload, and publication; use `sd-podcast start` as a shorter alias, or add `--approve` only for an intentionally unattended run.

An unchanged existing script is reused. Changed script turns must be reapproved; TTS segments are cached by voice/model/content; the final MP3 is stored locally only, outside Git. Publishing does not automatically push to GitHub, and you can stop before any paid step.

CLI operations report each blocking failure with an actionable next step and exit nonzero on failure. Transient speech and R2 upload errors use bounded exponential retries; rerunning a partially completed render reuses completed cached segments, and content-addressed uploads avoid duplicate media objects.

Each generation/render/upload/publish step writes a local, git-ignored `episodes/<slug>/run-report.json` and prints measured model usage, TTS characters actually synthesized (cached segments are excluded from the cost estimate), and estimated USD cost. Token counts come from API responses; estimates use the configured/default rates and mark the total unavailable when a model or provider has no rate.

## AI services and audio choices

- **Dialogue:** OpenAI Responses API, `SCRIPT_MODEL` configurable (`gpt-4.1-mini` example default). Two-pass generation: design brief then conversation; all source content is untrusted input.
- **Audio:** ElevenLabs Text-to-Speech REST API, distinct `ELEVENLABS_VOICE_A` and `ELEVENLABS_VOICE_B`, default `eleven_multilingual_v2` for stable, long-form voice consistency. Select voices from the official library and specify voice IDs in `.env`.
- **Free local audio testing:** Set `TTS_PROVIDER=local` on macOS to use built-in `say` voices (`LOCAL_VOICE_A` and `LOCAL_VOICE_B`) and ffmpeg, with no ElevenLabs API calls. This is useful for validating the pipeline; use ElevenLabs for production voice quality.
- **Google Cloud audio:** Set `TTS_PROVIDER=google`, provide `GOOGLE_CLOUD_AUDIO_API_KEY`, and configure distinct `GOOGLE_VOICE_A` and `GOOGLE_VOICE_B` voice names. The pipeline synthesizes each turn with the selected speaker voice and joins the resulting MP3 segments.

Google Cloud setup example:

```env
TTS_PROVIDER=google
GOOGLE_CLOUD_AUDIO_API_KEY=your-google-cloud-api-key
GOOGLE_TTS_LANGUAGE_CODE=en-US
GOOGLE_VOICE_A=en-US-Neural2-F
GOOGLE_VOICE_B=en-US-Neural2-J
```

To try local audio without ElevenLabs, set these values in `.env`:

```env
TTS_PROVIDER=local
LOCAL_VOICE_A=Samantha
LOCAL_VOICE_B=Alex
```

Check installed voice names with `say -v '?'`, then run the normal approved `render` command. Local audio is for development and still produces the same MP3 format and 20-minute validation path.
- **Editing/assembly:** ffmpeg joins per-turn MP3 files into a single standardized MP3; ffprobe validates duration.
- **Alternative providers:** Both script creation and speech synthesis are intentionally isolated in `writer.py` and `tts.py`. Replace or add a provider without changing the rest of the pipeline. OpenAI's older Speech API TTS models are scheduled to shut down in January 2027, so this starter does not depend on them.

**Cost note:** Both AI services bill usage; check provider pricing/quotas before running. The protected GitHub workflow runs only on manual dispatch to avoid automatic costly generation.

## Cloudflare R2 setup

1. Create an **R2 Standard** storage bucket, e.g. `system-design-audio`.
2. Configure public access for the *media* bucket using a Cloudflare custom domain (preferred for production traffic) or an `r2.dev` endpoint (rate-limited and intended for development; the two included episodes currently use one); test public HTTPS access. Consider CORS for custom player clients (native HTML audio commonly works without it).
3. Create a **bucket-scoped API token** with the minimum permissions needed for uploads. Avoid admin account tokens.
4. Put the account ID, bucket name, key/secret and public HTTPS base URL into `.env` (see `.env.example`). **Do not put these in the browser, HTML or repository.**
5. Media is stored at `episodes/<slug>/<content-hash>.mp3`. On reruns, this key is stable for unchanged audio. Uploaded objects are public by design; do not upload private recordings.

R2 Standard's published free tier is 10 GB-months storage, with request allowances; R2 has no egress fees but can still charge for storage/operations above allowances. See [R2 pricing](https://developers.cloudflare.com/r2/pricing/).

## GitHub Pages setup

1. Create a new GitHub repository named **`system-design-on-the-go`**, upload these files, and set the default branch to `main`.
2. Set `site_url` in `site.json` to `https://YOUR-USERNAME.github.io/system-design-on-the-go/` or your custom domain. Set `repo_url`, `name`, `description` and `author` as desired.
3. In the repo open **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. Push to `main`; `.github/workflows/pages.yml` builds `docs/` and deploys HTML, CSS and RSS. No keys are needed for the regular Pages workflow.
5. New published episodes appear at `/episodes/<slug>/`. The `<details>` transcript is initially closed; its contents remain readable and accessible without JavaScript.
6. RSS is at `/feed.xml` and includes only episodes that have real public audio URLs. Submitting the feed to podcast directories is optional and may need additional metadata/artwork.

GitHub Pages has usage limits. **Do not commit the large MP3s:** the source repo has a recommended 1 GB limit and Pages a soft 100 GB/month bandwidth limit. Audio streams directly from R2.

## Agent Skills

These are portable [`SKILL.md`](https://agentskills.io/specification) folders, discoverable by Codex, Cursor and other agents that support the format:

| Skill | Purpose |
|---|---|
| `.agents/skills/source-to-dialogue/` | Extract, ground, and review the collaborative script |
| `.agents/skills/dialogue-to-audio/` | Keep consistent speakers, cached TTS and MP3 QC |
| `.agents/skills/publish-episode/` | Upload to R2, build player, transcript, RSS |
| `.agents/skills/podcast-orchestrator/` | End-to-end run, checkpoints, idempotency, review controls |

Agents should read `AGENTS.md` then the task-specific skill, and operate the deterministic CLI rather than independently fabricating success status or publishing credentials.

## Safety, reliability and limitations

- **Prompt injection:** Sources are untrusted. Page text is not a user or system instruction; the LLM prompt explicitly treats it as data. Local URL validation blocks non-HTTPS/private address requests on a best-effort basis. For multi-tenant Internet-facing products, use a fully isolated fetch service to prevent DNS rebinding or SSRF attacks.
- **Code and CLI in sources:** Markdown fences and HTML code blocks are retained as non-spoken technical evidence for grounding, while the narrative source passed to dialogue generation omits them. The brief may preserve their architectural implications, but the spoken script must explain behavior in plain language without reproducing commands, flags, paths, syntax or copied snippets.
- **Source limits:** A run accepts 1–8 sources. Each source may download up to 2 MB, then keeps at most 16,000 characters of narrative text and 8,000 characters of code/CLI artifacts; larger pages are truncated.
- **Copyright and attribution:** Create original transformative discussions, credit sources and respect author licensing. Do not copy/publish full articles or unlicensed transcripts.
- **Accuracy:** AI scripts require human verification; the design brief exposes assumptions and uncertainty. No automated formal fact-check guarantee.
- **Research on gaps:** The source assessment triggers a required Responses API web-search pass when supplied material is too vague or incomplete. Cited HTTPS research links are saved in `episode.json` and rendered in the episode references; set `RESEARCH_ON_GAPS=false` only when deliberately stopping instead of filling the gaps.
- **Script edits:** Edit `episode.json` only (canonical source). The script hash enforces reapproval after changes and invalidates old audio.
- **Transcript format:** Source generation writes JSON `episode.json` using `conversation-v1`: ordered `{speaker, text}` turns with plain spoken text. HTML is a derived publication format generated later by `sd-podcast build-site`.
- **Secrets and prices:** Environment variables only; never check in credentials. AI and storage usage are not free in general.
- **Resumability:** Existing script and cached TTS turns are reused. On a failed upload/build, rerun the appropriate stage; partial changes are not published automatically.
- **Media QA:** ffprobe validates file duration and rejects episodes longer than 20 minutes, but humans should listen to spot pronunciation and pacing issues. Single mixed MP3 currently lacks chapter timings and music.
- **Publication:** Static website preview can be built offline, but actual voice calls, bucket access, Pages deployment and public reachability cannot be verified without live credentials.

## Tests

```bash
pytest -q
sd-podcast build-site
```

## Project layout

```text
.agents/skills/                 # four reusable, portable Agent Skills
.github/workflows/             # Pages deployment + opt-in episode generation
podcast_pipeline/              # ingestion, LLM, TTS, storage, HTML/RSS, CLI
episodes/<slug>/episode.json    # canonical script, references and publication state
episodes/<slug>/design-brief.json
                                # design brief and grounding metadata
episodes/<slug>/run-report.json  # local cost/usage report (git-ignored)
docs/                           # generated GitHub Pages site (no MP3s)
examples/                       # seed source notes
tests/                          # offline regression tests
```

MIT licensed. AI-generated voice disclosure appears on every episode page.
