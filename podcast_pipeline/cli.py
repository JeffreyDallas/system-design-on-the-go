"""Resumable CLI agent orchestrator for script -> audio -> R2 -> GitHub Pages."""
from __future__ import annotations

import argparse
from pathlib import Path

from .util import TRANSCRIPT_FORMAT, ROOT, episode_dir, read_json, save_json, script_hash, sha256, utcnow
from .writer import validate_script


def _load(slug: str) -> tuple[Path, dict]:
    folder = episode_dir(slug)
    path = folder / "episode.json"
    if not path.exists():
        raise FileNotFoundError(f"No episode at {path}. Run 'new' first")
    return folder, validate_script(read_json(path))


def _save(folder: Path, ep: dict) -> None:
    save_json(folder / "episode.json", ep)


def create_episode(slug: str, problem: str | None, sources: list[str] | None) -> tuple[Path, dict, bool]:
    folder = episode_dir(slug)
    if (folder / "episode.json").exists():
        folder, ep = _load(slug)
        print(f"Reusing existing script: {folder / 'episode.json'}")
        return folder, ep, False
    if not problem or not sources:
        raise ValueError("A new episode needs --problem and at least one --source")
    from .sources import collect_sources
    from .writer import generate

    folder.mkdir(parents=True, exist_ok=True)
    extracted = collect_sources(sources)
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
    from .tts import render_audio
    print("Generating two-voice audio; each completed segment is cached ...")
    path, seconds = render_audio(ep, folder)
    ep["rendered_script_hash"] = current
    ep["audio_sha256"] = sha256(path.read_bytes())
    ep["duration_seconds"] = round(seconds, 2)
    ep["audio_bytes"] = path.stat().st_size
    ep["audio_url"] = ""  # Invalidates any previous upload on script change
    ep.pop("storage_key", None)
    _save(folder, ep)
    print(f"Audio ready: {path} ({seconds / 60:.1f} min)")
    return ep


def upload(folder: Path, ep: dict) -> dict:
    path = folder / "episode.mp3"
    if not path.is_file() or ep.get("rendered_script_hash") != script_hash(ep):
        raise ValueError("Render the current approved script before uploading")
    digest = sha256(path.read_bytes())
    if ep.get("audio_url") and digest == ep.get("audio_sha256"):
        print("Already uploaded this audio; skipping duplicate upload")
        return ep
    from .storage import upload_audio
    result = upload_audio(path, ep["slug"])
    ep.update(result)
    _save(folder, ep)
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
    from .website import build_site
    if not ep.get("published_at"):
        ep["published_at"] = utcnow()
        _save(folder, ep)
    count, output = build_site()
    print(f"Site built: {output} ({count} episodes). Commit and push to publish via GitHub Actions.")
    return ep


def demo() -> None:
    folder = episode_dir("demo-distributed-rate-limiter")
    if not (folder / "episode.json").exists():
        ep = {
            "slug": "demo-distributed-rate-limiter",
            "transcript_format": TRANSCRIPT_FORMAT,
            "title": "Designing a Distributed Rate Limiter",
            "description": "Two colleagues compare a shared Redis counter with locally enforced token buckets, from consistency to failure recovery.",
            "problem": "Protect an API with a distributed rate limiter while keeping latency low and avoiding a shared-service outage taking down requests.",
            "created_at": utcnow(), "published_at": utcnow(), "references": [], "audio_url": "",
            "turns": [
                {"speaker":"A","text":"We need rate limits across multiple gateways. A per-process counter won't work if traffic lands on different instances, so my first thought is a shared store like Redis."},
                {"speaker":"B","text":"A shared counter simplifies enforcement, but now every request may depend on Redis latency and availability. Before we commit, how strict do our limits need to be?"},
                {"speaker":"A","text":"Let's say paid accounts require reasonably strict limits while anonymous traffic may tolerate small bursts. We should make that an explicit assumption, not present it as a known requirement."},
                {"speaker":"B","text":"Then we could try local token buckets for anonymous clients and a centralized counter for paid accounts. But consistency and failure handling still need careful testing."},
                {"speaker":"A","text":"For strict limits, an atomic Redis operation could update state and TTL together. It also gives us a place to collect rejects and saturation metrics."},
                {"speaker":"B","text":"And we need to ask what happens when Redis is unavailable. Do we fail open and risk overload, or fail closed and block paying customers? I'd prefer an explicit per-endpoint policy."},
                {"speaker":"A","text":"Agreed. Let's also test burst traffic, uneven gateway load and hot customer keys. That will tell us whether a single shard is adequate."},
                {"speaker":"B","text":"Our next step is a prototype and load test, not a premature final architecture. We can compare latency budgets, operational burden and the observed error rate."}
            ]
        }
        folder.mkdir(parents=True, exist_ok=True)
        _save(folder, ep)
    from .website import build_site
    count, out = build_site()
    print(f"Demo site created at {out / 'index.html'} ({count} episode previews). No paid APIs called.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sd-podcast", description="AI collaborative system design podcast workflow")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("new", "run"):
        p = sub.add_parser(command, help="Create a script, or execute the complete workflow")
        p.add_argument("--slug", required=True)
        p.add_argument("--problem")
        p.add_argument("--source", action="append", default=[])
        if command == "run":
            p.add_argument("--approve", action="store_true", help="Approve the current script and continue with paid TTS and upload")
    for command in ("render", "upload", "publish"):
        p = sub.add_parser(command)
        p.add_argument("--slug", required=True)
    sub.add_parser("build-site", help="Regenerate all GitHub Pages HTML and RSS files")
    sub.add_parser("demo", help="Create a source-free offline example; no TTS calls")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            demo()
        elif args.command == "build-site":
            from .website import build_site
            count, path = build_site()
            print(f"Built {count} episode pages in {path}")
        elif args.command in ("new", "run"):
            folder, ep, created = create_episode(args.slug, args.problem, args.source)
            if args.command == "new":
                print("Review and edit turns in episode.json, then run 'run --slug <slug> --approve'.")
                return
            if not args.approve and ep.get("approved_script_hash") != script_hash(ep):
                print("Review checkpoint. Edit episode.json as needed. Then rerun with --approve.")
                return
            if args.approve:
                ep = approve(folder, ep)
            current = script_hash(ep)
            if (ep.get("published_at") and ep.get("audio_url")
                and ep.get("approved_script_hash") == current
                and ep.get("rendered_script_hash") == current):
                from .website import build_site
                build_site()
                print("Already published this exact script; rebuilding website without TTS or upload")
                return
            ep = render(folder, ep)
            ep = upload(folder, ep)
            publish(folder, ep)
        else:
            folder, ep = _load(args.slug)
            if args.command == "render":
                render(folder, ep)
            elif args.command == "upload":
                upload(folder, ep)
            elif args.command == "publish":
                publish(folder, ep)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        parser.exit(2, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
