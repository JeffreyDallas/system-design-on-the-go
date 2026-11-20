import pytest

from podcast_pipeline import cli
from podcast_pipeline.util import script_hash


def _dummy_script():
    return {
        "title":"A Shared Cache Trade-off", "description":"Two peer engineers assess caching.",
        "turns":[{"speaker":"A" if i%2==0 else "B", "text":"Let's examine the latency, consistency, and operational impact."} for i in range(10)]
    }


def test_review_checkpoint_and_resume(monkeypatch, tmp_path):
    slug = 'cache-debate'
    monkeypatch.setattr(cli, 'episode_dir', lambda _: tmp_path / slug)
    monkeypatch.setattr(cli, 'collect_sources', lambda inputs: [{"id":"S1", "title":"Test", "url":"", "text":"Test sources"}])
    calls = {'n':0}
    def generate(problem, sources):
        calls['n'] += 1
        return {"requirements":["low latency"]}, _dummy_script()
    monkeypatch.setattr(cli, 'generate', generate)
    folder, ep, created = cli.create_episode(slug, 'A meaningful cache design problem', ['example.md'])
    assert created
    assert ep['transcript_format'] == 'conversation-v1'
    assert not ep['approved_script_hash']
    assert calls['n'] == 1
    _, _, created_again = cli.create_episode(slug, 'A changed prompt', ['example2.md'])
    assert not created_again
    assert calls['n'] == 1
    ep = cli.approve(folder, ep)
    assert ep['approved_script_hash'] == script_hash(ep)
    ep['turns'][0]['text'] += ' And revise the design.'
    with pytest.raises(ValueError, match='not approved'):
        cli.render(folder, ep)
    assert not (folder / 'episode.mp3').exists()


def test_publish_requires_audio_and_approval(tmp_path):
    folder = tmp_path / 'ep'
    folder.mkdir()
    ep = {'title':'Episode','description':'Desc','slug':'ep','turns':_dummy_script()['turns'],
          'audio_url':'', 'approved_script_hash':''}
    with pytest.raises(ValueError, match='approved script and uploaded audio'):
        cli.publish(folder, ep)


def test_stale_audio_cannot_be_published(tmp_path):
    folder = tmp_path / 'ep'
    folder.mkdir()
    ep = {'title':'Episode','description':'Desc','slug':'ep','turns':_dummy_script()['turns'],
          'audio_url':'https://audio.example.com/old.mp3',
          'approved_script_hash':'old', 'rendered_script_hash':'old'}
    ep['approved_script_hash'] = script_hash(ep)
    with pytest.raises(ValueError, match='matching the current script'):
        cli.publish(folder, ep)


def test_publish_rejects_replaced_audio(tmp_path):
    folder = tmp_path / 'ep'
    folder.mkdir()
    ep = {'title':'Episode','description':'Desc','slug':'ep','turns':_dummy_script()['turns'],
          'audio_url':'https://audio.example.com/old.mp3', 'audio_sha256':'original',
          'rendered_script_hash':'', 'approved_script_hash':''}
    ep['approved_script_hash'] = script_hash(ep)
    ep['rendered_script_hash'] = ep['approved_script_hash']
    (folder / 'episode.mp3').write_bytes(b'replaced')
    with pytest.raises(ValueError, match='matching the current script'):
        cli.publish(folder, ep)


def test_interactive_builder_collects_numbered_sources_and_runs_pipeline(monkeypatch, tmp_path):
    answers = iter([
        "2",
        "https://example.com/one",
        "notes.md",
        "yes",
    ])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    folder = tmp_path / "interactive-episode"
    folder.mkdir()
    ep = {"slug": "interactive-episode", "title": "Interactive Episode",
          "turns": _dummy_script()["turns"]}
    calls = []

    monkeypatch.setattr(cli, "collect_sources", lambda sources: [
        {"id": "S1", "title": "One", "url": sources[0], "text": "source one"},
        {"id": "S2", "title": "Two", "url": "", "text": "source two"},
    ])
    monkeypatch.setattr(cli, "infer_episode_context", lambda sources: (
        calls.append(("infer", sources)) or ("Interactive Episode", "Design a resilient event ingestion service")
    ))
    monkeypatch.setattr(cli, "create_episode", lambda slug, problem, sources: (
        calls.append((slug, problem, sources)) or (folder, ep, True)
    ))
    monkeypatch.setattr(cli, "approve_episode", lambda folder, episode: calls.append("approve") or episode)
    monkeypatch.setattr(cli, "render", lambda folder, episode: calls.append("render") or episode)
    monkeypatch.setattr(cli, "upload", lambda folder, episode: calls.append("upload") or episode)
    monkeypatch.setattr(cli, "publish", lambda folder, episode: calls.append("publish") or episode)

    cli.interactive_run()

    assert calls == [
        (None, None, ["https://example.com/one", "notes.md"]),
        "approve", "render", "upload", "publish",
    ]
