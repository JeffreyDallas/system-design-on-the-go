# System Design on the Go 🎧

**Two engineers. One problem. Better architecture.**

An open-source, agent-friendly system that turns system-design sources and engineering problems into a **two-engineer collaborative podcast**—not an interview, not a narrated article. An AI design brief drives real discussion of constraints, alternatives, operational behavior, and trade-offs. The result is a hosted MP3, a dedicated GitHub Pages episode, a **collapsed-by-default transcript**, source references and RSS.

> **Status:** Working starter project with offline-tested site generation, CLI orchestration, ElevenLabs TTS and Cloudflare R2 integration. Real API calls, cloud uploads and GitHub deployment require *your own credentials* and have not been executed in this starter.

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

Preview the site **without any AI credentials or API cost**:

```bash
sd-podcast demo
python -m http.server 8000 --directory docs
# Open http://localhost:8000/
```

The demo has a realistic eight-turn sample transcript and **no audio**; it deliberately says audio is not published. No live audio is included in the starter package.

## Create an episode, with review

```bash
sd-podcast run \
  --slug distributed-rate-limiter \
  --problem 'Design a distributed API rate limiter for 100,000 requests/second across regions, balancing strict customer quotas, latency, resilience and cost' \
  --source 'https://redis.io/docs/latest/develop/use/patterns/' \
  --source 'examples/rate-limiter-notes.md'
```

**This first invocation stops** after generating `episodes/distributed-rate-limiter/design-brief.json` and `episode.json`. Open and edit the canonical `episode.json` if needed; check that both engineers contribute, no source facts are invented, and technical trade-offs hold up. Then:

```bash
sd-podcast run --slug distributed-rate-limiter --approve
```

That second command renders voice audio, uploads it to R2, records the public MP3 URL and rebuilds the Pages website. `--approve` is an explicit skip/confirmation of the review checkpoint. For an unattended one-command run, include `--approve` in the *first* command. You can also run the stages independently:

```bash
sd-podcast new        --slug ... --problem '...' --source '...'
sd-podcast render     --slug ...
sd-podcast upload     --slug ...
sd-podcast publish    --slug ...
sd-podcast build-site
```

An unchanged existing script is reused. Changed script turns must be reapproved; TTS segments are cached by voice/model/content; the final MP3 is stored locally only, outside Git. Publishing does not automatically push to GitHub, and you can stop before any paid step.

## AI services and audio choices

- **Dialogue:** OpenAI Responses API, `SCRIPT_MODEL` configurable (`gpt-4.1-mini` example default). Two-pass generation: design brief then conversation; all source content is untrusted input.
- **Audio:** ElevenLabs Text-to-Speech REST API, distinct `ELEVENLABS_VOICE_A` and `ELEVENLABS_VOICE_B`, default `eleven_multilingual_v2` for stable, long-form voice consistency. Select voices from the official library and specify voice IDs in `.env`.
- **Free local audio testing:** Set `TTS_PROVIDER=local` on macOS to use built-in `say` voices (`LOCAL_VOICE_A` and `LOCAL_VOICE_B`) and ffmpeg, with no ElevenLabs API calls. This is useful for validating the pipeline; use ElevenLabs for production voice quality.

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
2. Configure public access for the *media* bucket using a Cloudflare custom domain (preferred) or a temporary `r2.dev` endpoint for development; test public HTTPS access. Consider CORS for custom player clients (native HTML audio commonly works without it).
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

## Optional unattended GitHub agent

`.github/workflows/publish-episode.yml` enables manual **Actions → Generate and publish a new podcast episode → Run workflow**. Supply `slug`, `problem`, and URLs (newline-separated). It performs all four stages with `--approve` and commits the new episode and Pages output. Its first run **will incur AI charges**, so consider required reviewers on the `podcast-production` environment.

Set environment/repository **secrets**: `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_A`, `ELEVENLABS_VOICE_B`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`. Set **variables**: `R2_BUCKET`, `R2_PUBLIC_BASE_URL`, and optional `SCRIPT_MODEL`, `ELEVENLABS_MODEL`. Actions workflow needs permission to push commits; check repo `Workflow permissions` and branch protection (protected branches may require a PR or bot exception).

For review-sensitive production use the local CLI instead. The workflow auto-approves without reading the generated script. Future extensions can split production into draft PR + human review + approved publish.

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
sd-podcast demo
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
docs/                           # generated GitHub Pages site (no MP3s)
examples/                       # seed source notes
tests/                          # offline regression tests
```

MIT licensed. AI-generated voice disclosure appears on every episode page.
