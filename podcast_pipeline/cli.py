"""Resumable CLI agent orchestrator for script -> audio -> R2 -> GitHub Pages."""
from __future__ import annotations

import argparse
import json
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from .sources import MAX_SOURCES, collect_sources
from .storage import upload_audio
from .tts import render_audio
from .util import TRANSCRIPT_FORMAT, episode_dir, read_json, save_json, script_hash, sha256, slug_check, slugify, utcnow
from .website import build_site
from .writer import generate, infer_episode_context, validate_script


@contextmanager
def progress(message: str):
    """Show a spinner in a terminal and plain progress lines in captured logs."""
    if not sys.stdout.isatty():
        print(f"{message} ...", flush=True)
        try:
            yield
        finally:
            print(f"{message} complete", flush=True)
        return
    stop = threading.Event()
    symbols = ("|", "/", "-", "\\")

    def spin() -> None:
        index = 0
        while not stop.is_set():
            sys.stdout.write(f"\r{symbols[index % len(symbols)]} {message}")
            sys.stdout.flush()
            index += 1
            stop.wait(0.12)

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        sys.stdout.write(f"\r✓ {message}\n")
        sys.stdout.flush()


def _write_run_report(folder: Path, ep: dict, *, generation=None, tts=None, stage="run") -> None:
    existing = read_json(folder / "run-report.json") if (folder / "run-report.json").exists() else {}
    generation = generation if generation is not None else existing.get("models", [])
    tts = tts if tts is not None else existing.get("tts", {})
    model_cost = sum(
        item["estimated_cost_usd"] for item in generation
        if item.get("estimated_cost_usd") is not None
    )
    unpriced_model_calls = sum(1 for item in generation if item.get("estimated_cost_usd") is None)
    tts_cost = (tts or {}).get("estimated_cost_usd")
    total = None if unpriced_model_calls or tts_cost is None else round(model_cost + tts_cost, 6)
    report = {
        "generated_at": utcnow(),
        "stage": stage,
        "slug": ep.get("slug"),
        "models": generation,
        "tts": tts or {},
        "estimated_total_cost_usd": total,
        "cost_note": "Estimates use configured/default list rates and exclude storage, egress, and unpriced tool calls.",
    }
    path = folder / "run-report.json"
    save_json(path, report)


def _print_run_report(folder: Path) -> None:
    """Print the final usage summary once per top-level command."""
    report = read_json(folder / "run-report.json")
    total = report.get("estimated_total_cost_usd")
    print(f"Usage report: {folder / 'run-report.json'}")
    print(f"Estimated AI cost: {'unavailable' if total is None else f'${total:.4f}'}")


def _load(slug: str) -> tuple[Path, dict]:
    slug_check(slug)
    folder = episode_dir(slug)
    path = folder / "episode.json"
    if not path.exists():
        raise FileNotFoundError(f"No episode at {path}. Run 'new' first")
    episode = validate_script(read_json(path))
    if episode.get("slug") != slug:
        raise ValueError("Episode slug does not match its directory")
    return folder, episode


def _save(folder: Path, ep: dict) -> None:
    save_json(folder / "episode.json", ep)


def create_episode(slug: str | None, problem: str | None, sources: list[str] | None) -> tuple[Path, dict, bool]:
    if slug:
        slug_check(slug)
        folder = episode_dir(slug)
        if (folder / "episode.json").exists():
            folder, ep = _load(slug)
            print(f"Reusing existing script: {folder / 'episode.json'}")
            return folder, ep, False
    if not sources:
        raise ValueError("A new episode needs at least one --source")
    with progress("Collecting source resources"):
        extracted = collect_sources(sources)
    context_usage = []
    if problem is None or slug is None:
        with progress("Inferring title, slug, and engineering problem"):
            inferred_title, inferred_problem = infer_episode_context(extracted)
        context_usage = getattr(infer_episode_context, "last_usage", [])
        problem = problem or inferred_problem
        slug = slug or slugify(inferred_title)
    slug_check(slug)
    folder = episode_dir(slug)
    if (folder / "episode.json").exists():
        folder, ep = _load(slug)
        print(f"Reusing existing script: {folder / 'episode.json'}")
        return folder, ep, False
    folder.mkdir(parents=True, exist_ok=True)
    with progress("Generating design brief and dialogue"):
        brief, draft = generate(problem, extracted)
    save_json(folder / "design-brief.json", brief)
    research_refs = brief.get("research", {}).get("sources", [])
    ep = {
        "slug": slug,
        "transcript_format": TRANSCRIPT_FORMAT,
        "title": draft["title"],
        "description": draft["description"],
        "problem": problem,
        "created_at": utcnow(),
        "references": ([{k:s[k] for k in ("id", "title", "url")} for s in extracted]
                       + research_refs),
        "turns": draft["turns"],
        "approved_script_hash": "",
        "rendered_script_hash": "",
        "audio_url": "",
    }
    _save(folder, ep)
    _write_run_report(folder, ep, generation=context_usage + getattr(generate, "last_usage", []), stage="new")
    print(f"Script created: {folder / 'episode.json'}")
    print(f"Design brief: {folder / 'design-brief.json'}")
    return folder, ep, True


def approve(folder: Path, ep: dict) -> dict:
    ep["approved_script_hash"] = script_hash(ep)
    _save(folder, ep)
    return ep


def render(folder: Path, ep: dict) -> dict:
    current = script_hash(ep)
    if ep.get("approved_script_hash") != current:
        raise ValueError("Script is not approved or changed after approval; rerun 'run --approve'")
    audio_file = folder / "episode.mp3"
    if ep.get("rendered_script_hash") == current and audio_file.is_file():
        print("Audio unchanged; using cached episode.mp3")
        return ep
    print("Generating two-voice audio; each completed segment is cached ...")
    with progress("Rendering two-voice audio"):
        path, seconds = render_audio(ep, folder)
    ep["rendered_script_hash"] = current
    ep["audio_sha256"] = sha256(path.read_bytes())
    ep["duration_seconds"] = round(seconds, 2)
    ep["audio_bytes"] = path.stat().st_size
    ep["audio_url"] = ""  # Invalidates any previous upload on script change
    ep.pop("storage_key", None)
    _save(folder, ep)
    _write_run_report(folder, ep, tts=getattr(render_audio, "last_usage", {}), stage="render")
    print(f"Audio ready: {path} ({seconds / 60:.1f} min)")
    return ep


def upload(folder: Path, ep: dict) -> dict:
    slug_check(ep.get("slug", ""))
    path = folder / "episode.mp3"
    if not path.is_file() or ep.get("rendered_script_hash") != script_hash(ep):
        raise ValueError("Render the current approved script before uploading")
    digest = sha256(path.read_bytes())
    if ep.get("audio_url") and digest == ep.get("audio_sha256"):
        print("Already uploaded this audio; skipping duplicate upload")
        return ep
    with progress("Uploading audio"):
        result = upload_audio(path, ep["slug"])
    ep.update(result)
    _save(folder, ep)
    _write_run_report(folder, ep, stage="upload")
    print(f"Audio available at: {ep['audio_url']}")
    return ep


def publish(folder: Path, ep: dict) -> dict:
    audio_file = folder / "episode.mp3"
    current_script_hash = script_hash(ep)
    audio_matches_metadata = (
        audio_file.is_file()
        and bool(ep.get("audio_sha256"))
        and sha256(audio_file.read_bytes()) == ep.get("audio_sha256")
    )
    if (not ep.get("audio_url") or ep.get("approved_script_hash") != current_script_hash
            or ep.get("rendered_script_hash") != current_script_hash or not audio_matches_metadata):
        raise ValueError("Published episodes require approved script and uploaded audio matching the current script")
    if not ep.get("published_at"):
        ep["published_at"] = utcnow()
        _save(folder, ep)
    with progress("Building the website and RSS feed"):
        count, output = build_site()
    _write_run_report(folder, ep, stage="publish")
    print(f"Site built: {output} ({count} episodes). Commit and push to publish via GitHub Actions.")
    return ep


def _prompt_text(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Please enter a value.")


def _prompt_source_count() -> int:
    while True:
        raw = _prompt_text(f"How many source resources? (1-{MAX_SOURCES}): ")
        try:
            count = int(raw)
        except ValueError:
            count = 0
        if 1 <= count <= MAX_SOURCES:
            return count
        print(f"Enter a whole number from 1 to {MAX_SOURCES}.")


def interactive_run(*, approve: bool = False) -> None:
    """Run the end-to-end workflow through an interactive CLI session."""
    print("System Design on the Go — interactive episode builder")
    source_count = _prompt_source_count()
    sources = [
        _prompt_text(f"Resource {index} (HTTPS URL or .md/.txt path): ")
        for index in range(1, source_count + 1)
    ]
    print("\nBuild plan")
    print("  Episode title and engineering problem: inferred from resources")
    print(f"  Resources: {len(sources)}")
    print("  Stages: collect → design brief → dialogue → review → audio → upload → site")
    folder, ep, created = create_episode(None, None, sources)
    print(f"  Inferred title: {ep['title']}")
    print(f"  Inferred slug: {ep['slug']}")
    if not created:
        print("Existing episode found; resuming its current state.")
    current = script_hash(ep)
    if (ep.get("published_at") and ep.get("audio_url")
            and ep.get("approved_script_hash") == current
            and ep.get("rendered_script_hash") == current):
        build_site()
        print("Already published this exact script; rebuilt the website without paid stages.")
        _print_run_report(folder)
        return
    if not approve:
        print(f"Review the generated script at {folder / 'episode.json'}.")
        if _prompt_text("Continue to paid audio and publication after review? [y/N]: ").lower() not in {"y", "yes"}:
            print("Paused at the human review checkpoint.")
            _print_run_report(folder)
            return
    ep = approve_episode(folder, ep)
    ep = render(folder, ep)
    ep = upload(folder, ep)
    publish(folder, ep)
    _print_run_report(folder)


def approve_episode(folder: Path, ep: dict) -> dict:
    """Approve a script after an interactive review or explicit --approve."""
    return approve(folder, ep)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sd-podcast", description="AI collaborative system design podcast workflow")
    sub = parser.add_subparsers(dest="command", required=True)
    for command, summary in (
        ("new", "Create a draft script and stop for review"),
        ("run", "Create or resume the script, then render, upload and publish"),
    ):
        p = sub.add_parser(command, help=summary, description=summary)
        p.add_argument("--slug", help="Optional existing episode identifier; new episodes infer it from sources")
        p.add_argument("--source", action="append", default=[],
                       help="Local .md/.txt file or public HTTPS URL; repeat for up to 8 sources")
        if command == "run":
            p.add_argument("--approve", action="store_true", help="Approve the current script and continue with paid TTS and upload")
    interactive = sub.add_parser("interactive", aliases=["start"], help="Interactively collect inputs and build an episode", description="Interactively collect inputs and build an episode")
    interactive.add_argument("--approve", action="store_true", help="Skip the interactive human review prompt")
    for command, summary in (
        ("render", "Synthesize the approved script into one MP3"),
        ("upload", "Upload the rendered MP3 to Cloudflare R2"),
        ("publish", "Rebuild the static Pages site and RSS feed"),
    ):
        p = sub.add_parser(command, help=summary, description=summary)
        p.add_argument("--slug", required=True)
    sub.add_parser("build-site", help="Regenerate all GitHub Pages HTML and RSS files")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-site":
            count, path = build_site()
            print(f"Built {count} episode pages in {path}")
        elif args.command in ("interactive", "start"):
            interactive_run(approve=args.approve)
        elif args.command in ("new", "run"):
            folder, ep, created = create_episode(args.slug, None, args.source)
            if args.command == "new":
                print("Review and edit turns in episode.json, then run 'run --slug <slug> --approve'.")
                _print_run_report(folder)
                return
            if not args.approve and ep.get("approved_script_hash") != script_hash(ep):
                parser.exit(2, "Review checkpoint: edit and review episode.json, then rerun with --approve.\n")
            if args.approve:
                ep = approve(folder, ep)
            current = script_hash(ep)
            if (ep.get("published_at") and ep.get("audio_url")
                and ep.get("approved_script_hash") == current
                and ep.get("rendered_script_hash") == current):
                build_site()
                print("Already published this exact script; rebuilding website without TTS or upload")
                _print_run_report(folder)
                return
            ep = render(folder, ep)
            ep = upload(folder, ep)
            publish(folder, ep)
            _print_run_report(folder)
        else:
            folder, ep = _load(args.slug)
            if args.command == "render":
                render(folder, ep)
            elif args.command == "upload":
                upload(folder, ep)
            elif args.command == "publish":
                publish(folder, ep)
            _print_run_report(folder)
    except Exception as exc:
        detail = str(exc).strip() or "No additional details were provided."
        action = "Check the command inputs and .env configuration, then retry."
        name = type(exc).__name__
        if isinstance(exc, FileNotFoundError):
            action = "Run the prerequisite command shown in the error, or verify the referenced path."
        elif isinstance(exc, json.JSONDecodeError):
            action = "Fix the malformed JSON file, then rerun the command."
        elif "approved" in detail.lower() or "review checkpoint" in detail.lower():
            action = "Review episode.json and rerun with --approve only after accepting the transcript."
        elif "missing" in detail.lower() and "configure .env" in detail.lower():
            action = "Set the named variable in .env, verify it is not replace_me, and rerun."
        elif "403" in detail or "401" in detail or "Unauthorized" in detail:
            action = "Verify the API key, enabled API, billing, and key restrictions, then wait a few minutes and retry."
        elif "429" in detail or "timeout" in detail.lower() or "temporarily" in detail.lower():
            action = "Wait for the provider to recover and rerun; completed cached segments will be reused."
        elif "ffmpeg" in detail.lower() or "ffprobe" in detail.lower():
            action = "Install ffmpeg and ffprobe, confirm they are on PATH, then rerun."
        elif "R2" in detail or "bucket" in detail.lower():
            action = "Verify R2 credentials, bucket name, public URL, and network access, then rerun."
        print(f"Error [{name}]: {detail}\nAction: {action}", file=sys.stderr)
        parser.exit(2)


if __name__ == "__main__":
    main()
