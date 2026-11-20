"""No framework required: accessible, sanitized static HTML and podcast RSS."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
import shutil
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

from .util import ROOT, read_json, secure_https_url, slug_check


def h(s) -> str:
    return escape(str(s or ""), quote=True)


def public_link(url: str) -> str:
    try:
        return secure_https_url(url)
    except ValueError:
        return ""


def base_html(title: str, content: str, relative: str, meta_description: str) -> str:
    config = read_json(ROOT / "site.json")
    repo_url = public_link(config.get("repo_url", ""))
    repo_link = (f'<a href="{h(repo_url)}" target="_blank" rel="noopener noreferrer">Source code</a>'
                 if repo_url and "YOUR-USERNAME" not in repo_url else "")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{h(meta_description)}"><meta name="theme-color" content="#101b27">
<title>{h(title)} — System Design on the Go</title>
<link rel="stylesheet" href="{relative}assets/styles.css"><link rel="stylesheet" href="{relative}assets/player.css">
<link rel="alternate" type="application/rss+xml" title="Podcast RSS" href="{relative}feed.xml"></head>
<body><a class="skip" href="#main">Skip to content</a><div class="shell">
<header class="masthead"><a class="brand" href="{relative}"><span class="brand-mark">S</span> System Design <span class="muted">on the Go</span></a>
<nav><a href="{relative}">Episodes</a><a href="{relative}feed.xml">RSS</a>{repo_link}</nav></header>
<main id="main">{content}</main>
<footer>AI-generated voices and dialogue. Verify engineering decisions against their sources. <span>© System Design on the Go</span><br>
Copyright concern? <a href="{h(public_link(config.get('copyright_contact_url', '')) or repo_url)}" target="_blank" rel="noopener noreferrer">Contact us to request review or removal.</a></footer>
</div></body></html>'''


def episode_html(ep: dict) -> str:
    title = ep["title"]
    audio = public_link(ep.get("audio_url", ""))
    player = (f'<div class="player"><div class="eyebrow">LISTEN TO EPISODE</div>'
              f'<audio controls autoplay preload="auto" data-episode-audio aria-label="Play {h(title)}"><source src="{h(audio)}" type="audio/mpeg">Your browser does not support the audio element.</audio>'
              '<div class="audio-controls" aria-label="Playback controls">'
              '<button type="button" class="audio-button" data-seek="-15" aria-label="Rewind 15 seconds">↶ 15s</button>'
              '<button type="button" class="audio-button" data-seek="15" aria-label="Forward 15 seconds">15s ↷</button>'
              '<label class="speed-control" for="playback-speed">Speed</label>'
              '<select id="playback-speed" class="speed-select" data-playback-speed aria-label="Playback speed">'
              '<option value="0.75">0.75×</option><option value="1" selected>1×</option>'
              '<option value="1.25">1.25×</option><option value="1.5">1.5×</option>'
              '<option value="2">2×</option></select></div>'
              f'<p class="small">Two AI-generated voices • {h(round(ep.get("duration_seconds", 0)/60))} min</p></div>') if audio else '<div class="notice">Audio is not published yet. Transcript preview is available below.</div>'
    turns = "\n".join(
        f'<div class="turn"><div class="speaker s{h(t["speaker"])}">Engineer {h(t["speaker"])}</div><p>{h(t["text"])}</p></div>'
        for t in ep["turns"]
    )
    references = []
    for ref in ep.get("references", []):
        url = public_link(ref.get("url", ""))
        if url:
            references.append(f'<li><a href="{h(url)}" target="_blank" rel="noopener noreferrer">{h(ref["title"])}</a> <span class="small">({h(ref["id"])})</span></li>')
        else:
            references.append(f'<li>{h(ref["title"])} <span class="small">(local reference {h(ref["id"])})</span></li>')
    source_section = f'<section class="sources"><h2>Sources and further reading</h2><ol>{"".join(references)}</ol></section>' if references else ''
    date = ep.get("published_at", ep.get("created_at", ""))[:10]
    content = f'''<div class="back"><a href="../../">← All episodes</a></div>
<section class="hero episode-hero"><div class="eyebrow">COLLABORATIVE SYSTEM DESIGN · {h(date)}</div>
<h1>{h(title)}</h1><p class="lede">{h(ep.get('description', ''))}</p>
<p class="problem"><strong>Design challenge:</strong> {h(ep.get('problem', ''))}</p></section>
{player}
<section class="transcript"><details><summary><span>Read the full conversation</span><span class="hint">Transcript hidden by default • Expand</span></summary>
<div class="transcript-body">{turns}</div></details></section>
{source_section}
<section class="notice disclosure"><strong>Transparency:</strong> This is a synthetic discussion between AI voices, not a recording of real engineers. Technical claims require independent verification.</section>'''
    page = base_html(title, content, "../../", ep.get("description", ""))
    if audio:
        page = page.replace('</body>', '''<script>
(() => {
  const audio = document.querySelector('[data-episode-audio]');
  if (!audio) return;
  audio.play().catch(() => {
    const notice = document.createElement('p');
    notice.className = 'small autoplay-notice';
    notice.textContent = 'Autoplay was blocked by your browser. Press play to start listening.';
    audio.insertAdjacentElement('afterend', notice);
  });
  document.querySelectorAll('[data-seek]').forEach((button) => {
    button.addEventListener('click', () => {
      const delta = Number(button.dataset.seek);
      const target = Math.max(0, audio.currentTime + delta);
      audio.currentTime = Number.isFinite(audio.duration) ? Math.min(target, audio.duration) : target;
    });
  });
  const speed = document.querySelector('[data-playback-speed]');
  speed.addEventListener('change', () => { audio.playbackRate = Number(speed.value); });
})();
</script></body>''')
    return page


def index_html(episodes: list[dict], config: dict) -> str:
    cards = []
    for ep in episodes:
        minutes = (f'{round(ep.get("duration_seconds", 0)/60)} min' if ep.get("duration_seconds") else "Audio coming soon")
        cards.append(f'''<article class="episode-card"><div class="eyebrow">{h(ep.get('published_at',ep.get('created_at',''))[:10])} · {h(minutes)}</div>
<h2><a href="episodes/{h(ep['slug'])}/">{h(ep['title'])}</a></h2>
<p>{h(ep.get('description',''))}</p><a class="readmore" href="episodes/{h(ep['slug'])}/">Explore episode →</a></article>''')
    cards_html = "".join(cards) or '<p class="notice">No episodes published yet. Create your first episode to get started.</p>'
    content = f'''<section class="hero"><div class="eyebrow">AN ENGINEERING PODCAST, BUILT BY AGENTS</div>
<h1>Better system design starts with a <em>conversation.</em></h1>
<p class="lede">{h(config.get('tagline','Two engineers. One problem. Better architecture.'))}</p>
<p class="sublede">Architecture decisions, real-world trade-offs and failure scenarios—explored by two peer engineers, then turned into audio you can enjoy anywhere.</p>
<a class="primary" href="#episodes">Browse episodes ↓</a></section>
<section id="episodes"><div class="sectionhead"><h2>Episodes</h2><a href="feed.xml">Subscribe via RSS ↗</a></div><div class="episode-grid">{cards_html}</div></section>'''
    return base_html("Episodes", content, "", config.get("description", ""))


def feed_xml(episodes: list[dict], config: dict) -> bytes:
    root_url = secure_https_url(config["site_url"])
    if not root_url.endswith("/"):
        root_url += "/"
    ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0")
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    for key, val in (("title",config["name"]),("link",root_url),("description",config["description"]),("language",config.get("language","en-US"))):
        ET.SubElement(channel,key).text=val
    ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0}author").text = config.get("author",config["name"])
    for ep in episodes:
        url = public_link(ep.get("audio_url", ""))
        if not url:
            continue
        item = ET.SubElement(channel,"item")
        for k, v in (("title",ep["title"]),( "description",ep.get("description","")),("link",urljoin(root_url,f"episodes/{ep['slug']}/")),("guid",urljoin(root_url,f"episodes/{ep['slug']}/"))):
            ET.SubElement(item,k).text=v
        stamp = datetime.fromisoformat(ep["published_at"].replace("Z","+00:00"))
        ET.SubElement(item,"pubDate").text=format_datetime(stamp.astimezone(timezone.utc))
        ET.SubElement(item,"enclosure",attrib={"url":url,"length":str(ep.get("audio_bytes",0)),"type":"audio/mpeg"})
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def build_site() -> tuple[int,Path]:
    site = ROOT / "docs"
    config = read_json(ROOT / "site.json")
    episodes = []
    for filepath in sorted((ROOT / "episodes").glob("*/episode.json")):
        ep = read_json(filepath)
        if ep.get("published_at"):
            slug = slug_check(ep.get("slug", ""))
            if slug != filepath.parent.name:
                raise ValueError("Episode slug does not match its directory")
            episodes.append(ep)
    episodes.sort(key=lambda ep: ep.get("published_at", ""), reverse=True)
    generated_slugs = {ep["slug"] for ep in episodes}
    episode_root = site / "episodes"
    if episode_root.is_dir():
        for child in episode_root.iterdir():
            if child.is_dir() and child.name not in generated_slugs:
                shutil.rmtree(child)
    for ep in episodes:
        folder = site / "episodes" / ep["slug"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.html").write_text(episode_html(ep), encoding="utf-8")
    site.mkdir(exist_ok=True)
    (site / ".nojekyll").touch()
    (site / "index.html").write_text(index_html(episodes, config), encoding="utf-8")
    (site / "feed.xml").write_bytes(feed_xml(episodes, config))
    return len(episodes), site
