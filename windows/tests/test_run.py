"""PrepProgress, PipelineRun, PipelineEnvironment, AIConfig: the same cases as the Swift tests."""

import json

from neuralloop_desktop.core import aiconfig, pipeline_run, prep

MIN = 60_000.0
SAMPLE = """{"updated": 1000000, "ended": false, "pid": 7,
 "items": [
   {"n": 1, "item": "audio", "by": "NotebookLM", "step": "NotebookLM is recording the podcast",
    "started": 1000000, "done": null, "total": null, "expected": 480},
   {"n": 1, "item": "quiz", "by": "Ollama", "step": "Voicing the podcast", "started": 1000000, "done": 12,
    "total": 40, "expected": null}],
 "queue": [{"n": 1, "item": "video"}, {"n": 2, "item": "audio"}, {"n": 2, "item": "video"}]}"""


def feed(text: str) -> dict:
    out = prep.read_activity(text.encode())
    assert out is not None
    return out


def item(a: dict, n: int, name: str) -> dict:
    return next(i for i in a["items"] if i["n"] == n and i["item"] == name)


def test_the_feed_says_whats_being_made_and_whats_in_line():
    a = feed(SAMPLE)
    assert item(a, 1, "audio")["by"] == "NotebookLM"
    assert [q["item"] for q in a["queue"]] == ["video", "audio", "video"]
    assert [prep.place_text(i) for i in (0, 1, 2, 10)] == [
        "Next up",
        "2nd in line",
        "3rd in line",
        "11th in line",
    ]
    assert prep.read_activity(b"nope") is None
    odd = feed(
        '{"items": [{"n": "x"}, {"n": 2, "item": "audio", "by": "NotebookLM", "started": 5}], "queue": "no"}'
    )
    assert len(odd["items"]) == 1 and odd["queue"] == [] and not odd["ended"]


def test_counted_work_shows_how_far_along_and_how_long_is_left():
    p = prep.item_progress(item(feed(SAMPLE), 1, "quiz"), 1_000_000 + 4 * MIN)
    assert abs(p["fraction"] - 0.3) < 0.001
    assert p["detail"] == "12 of 40 · 4 min so far · about 9 min left" and not p["slow"]


def test_notebooklm_work_is_timed_against_how_long_it_usually_takes():
    it = item(feed(SAMPLE), 1, "audio")
    early = prep.item_progress(it, 1_000_000 + 2 * MIN)
    assert 0.15 < early["fraction"] < 0.35 and early["detail"] == "2 min so far · about 6 min left"
    nearly = prep.item_progress(it, 1_000_000 + 7.6 * MIN)
    assert nearly["detail"] == "8 min so far · almost there" and nearly["fraction"] < 0.95
    slow = prep.item_progress(it, 1_000_000 + 15 * MIN)
    assert slow["slow"] and nearly["fraction"] < slow["fraction"] < 0.99
    assert (
        slow["detail"].startswith("15 min so far")
        and "NotebookLM can be slow when it's busy" in slow["detail"]
    )


def test_a_slow_local_item_doesnt_blame_notebooklm_and_quick_ones_arent_slow():
    a = feed(
        '{"items": [{"n": 1, "item": "study", "by": "Ollama", "step": "x", "started": 0, "expected": 60}]}'
    )
    slow = prep.item_progress(item(a, 1, "study"), 10 * MIN)
    assert slow["slow"] and slow["detail"] == "10 min so far, longer than usual. It's still going."
    a = feed(
        '{"items": [{"n": 1, "item": "cards", "by": "NotebookLM", "step": "x", "started": 0, '
        '"expected": 20}]}'
    )
    p = prep.item_progress(item(a, 1, "cards"), 27_000)
    assert not p["slow"] and p["detail"] == "Just started · almost there"
    assert prep.item_progress(item(a, 1, "cards"), 2 * MIN)["detail"].startswith(
        "2 min so far, longer than usual"
    )


def test_with_no_count_and_no_estimate_the_bar_just_moves():
    a = feed('{"items": [{"n": 1, "item": "video", "by": "Ollama", "step": "Writing", "started": 0}]}')
    p = prep.item_progress(item(a, 1, "video"), 3 * MIN)
    assert p["fraction"] is None and p["detail"] == "3 min so far" and prep.percent_text(p) is None
    assert feed('{"ended": true, "items": [], "queue": []}')["ended"]


def test_every_measurable_item_shows_a_percentage_and_estimates_say_so():
    a = feed("""{"items": [
      {"n": 1, "item": "video", "by": "Ollama", "step": "d", "started": 0, "done": 50, "total": 100,
       "fraction": 0.69},
      {"n": 1, "item": "audio", "by": "NotebookLM", "step": "r", "started": 0, "expected": 480},
      {"n": 2, "item": "audio", "by": "Ollama", "step": "v", "started": 0, "done": 10, "total": 40}]}""")
    video = prep.item_progress(item(a, 1, "video"), 6.9 * MIN)
    assert video["fraction"] == 0.69 and prep.percent_text(video) == "69%"
    assert video["detail"] == "50 of 100 · 7 min so far · about 3 min left"
    podcast = prep.item_progress(item(a, 1, "audio"), 3 * MIN)
    assert prep.percent_text(podcast) == "About 34%"
    assert prep.percent_text(prep.item_progress(item(a, 2, "audio"), MIN)) == "25%"


def test_just_started_items_read_as_one_sentence():
    a = feed(
        '{"items": [{"n": 1, "item": "video", "by": "NotebookLM", "step": "x", "started": 0, '
        '"expected": 720}]}'
    )
    assert prep.item_progress(item(a, 1, "video"), 20_000)["detail"] == "Just started · about 12 min left"
    a = feed(
        '{"items": [{"n": 1, "item": "video", "by": "O", "step": "x", "started": 0, "done": 50, '
        '"total": 100, "fraction": 0.5}]}'
    )
    assert (
        prep.item_progress(item(a, 1, "video"), 20_000)["detail"] == "50 of 100 · just started · almost there"
    )


def test_reads_every_progress_line():
    parse = pipeline_run.parse_line
    assert parse("  ✓ chapter 1 quiz (12s)") == {"kind": "made", "chapter": 1, "item": "quiz"}
    assert parse("  ↪ chapter 2 audio: NotebookLM couldn't (limit); making it with Ollama") == {
        "kind": "fellBack",
        "chapter": 2,
        "item": "audio",
        "to": "Ollama",
    }
    assert parse("  … chapter 3 video: Claude limit reached; will continue next run") == {
        "kind": "waiting",
        "chapter": 3,
        "item": "video",
    }
    assert parse("  ✗ chapter 4 cards: UnusableAnswer: nope") == {
        "kind": "failed",
        "chapter": 4,
        "item": "cards",
        "reason": "UnusableAnswer: nope",
    }
    assert parse("  added chapter 5: Queues") == {"kind": "added", "chapter": 5}
    assert parse("  setup: downloading qwen3:8b 50%") == {"kind": "setup", "text": "downloading qwen3:8b 50%"}
    assert parse("Book: C:\\lib\\book") == {"kind": "finished"}
    assert parse("Making 7 items.") == {"kind": "note", "text": "Making 7 items."}


def test_book_ids_are_safe_folder_names():
    assert pipeline_run.slug("Designing Data-Intensive Applications (2nd ed.)") == (
        "designing-data-intensive-applications-2nd-ed"
    )
    assert pipeline_run.slug("!!!") == "book"
    assert pipeline_run.is_valid_id("my-book-2") and not pipeline_run.is_valid_id("../etc")
    assert not pipeline_run.is_valid_id("") and not pipeline_run.is_valid_id("con\\x")
    assert pipeline_run.unique("caching", {"caching", "caching-2"}) == "caching-3"


def test_the_pipeline_command_carries_the_choices_but_never_keys():
    args = pipeline_run.arguments("C:/b/Caching.epub", "C:/lib/caching", "all", "1-2", dry_run=True)
    assert args == [
        "C:/b/Caching.epub",
        "--out",
        "C:/lib/caching",
        "--no-open",
        "--chapters",
        "all",
        "--media",
        "1-2",
        "--dry-run",
    ]
    args = pipeline_run.arguments("/b.pdf", "/lib/b", "all", "1", retry=True, engine="local", title="-Draft")
    assert args[-3:] == ["--engine", "local", "--title=-Draft"] and "--retry" in args


def test_titles_come_from_what_the_person_called_it_or_the_file():
    assert pipeline_run.title_for_file("C:\\Users\\me\\Desktop\\Agents_guide.pdf") == "Agents guide"
    assert pipeline_run.title_for_file("/x/deep-learning--2nd_ed.epub") == "deep learning 2nd ed"
    assert pipeline_run.title_for_file("/x/___.pdf") is None
    inbox = "/lib/inbox/3f2a9c1e-7b4d-4e8a-9c0f-1a2b3c4d5e6f.pdf"
    assert pipeline_run.book_title("  Caching\nnotes ", inbox) == "Caching notes"
    assert pipeline_run.book_title(None, inbox) == "Your book"
    assert pipeline_run.book_title(None, "/x/___.pdf") == "Your book"
    sneaky = "\u202eCaching\u202c \u2066notes\u2069\u200b\u2060\ufeff\u200e\u200f"
    assert pipeline_run.book_title(sneaky, inbox) == "Caching notes"
    assert pipeline_run.book_title("Family 👩\u200d👧 notes", inbox) == "Family 👩\u200d👧 notes"
    assert pipeline_run.saved_title("  ", "C:/Users/me/node.js_guide.pdf") == "node.js guide"
    assert pipeline_run.saved_title("\u200b", None) is None and pipeline_run.saved_title(None, None) is None


def test_only_the_persons_saved_keys_and_settings_reach_the_pipeline():
    inherited = {
        "PATH": "C:\\Windows",
        "SYSTEMROOT": "C:\\Windows",
        "ANTHROPIC_API_KEY": "shell",
        "OPENROUTER_API_KEY": "shell",
        "NEURALLOOP_BASE_URL": "http://x",
        "NEURALLOOP_AI_CONFIG": "/o.json",
        "ANTHROPIC_BASE_URL": "http://x",
        "AZURE_OPENAI_ENDPOINT": "http://x",
        "Openai_Org_Id": "x",
    }
    env = pipeline_run.environment(
        inherited, {"OPENAI_API_KEY": "saved", "ANTHROPIC_API_KEY": "", "OTHER": "x"}, "C:/ai.json"
    )
    assert (
        env["OPENAI_API_KEY"] == "saved"
        and "ANTHROPIC_API_KEY" not in env
        and "OPENROUTER_API_KEY" not in env
    )
    assert "NEURALLOOP_BASE_URL" not in env and env["NEURALLOOP_AI_CONFIG"] == "C:/ai.json"
    assert (
        "ANTHROPIC_BASE_URL" not in env and "AZURE_OPENAI_ENDPOINT" not in env and "Openai_Org_Id" not in env
    )
    assert "OTHER" not in env and env["SYSTEMROOT"] == "C:\\Windows"
    assert env["PYTHONUNBUFFERED"] == "1" and env["PYTHONIOENCODING"] == "utf-8"


def test_reads_and_writes_the_same_ai_json_as_the_pipeline():
    raw = {
        "engine": "local",
        "make": {"provider": "anthropic", "model": "claude-opus-5"},
        "tasks": {"quiz": {"provider": "ollama", "model": "qwen3:8b"}},
        "recall": {"provider": "ollama", "model": "gemma2:2b"},
        "voices": ["af_bella", "bm_george"],
        "voiceQuality": "best",
        "audioLength": "short",
        "hermesTools": True,
    }
    config = aiconfig.parse(raw)
    assert config == raw and aiconfig.parse(json.loads(aiconfig.encode(config))) == config
    d = aiconfig.parse({})
    assert d["engine"] == "auto" and d["make"] == {"provider": "auto"} and d["voiceQuality"] == "fast"
    assert aiconfig.parse({"voices": ["one"], "engine": "x"})["voices"] == ["af_heart", "am_michael"]


def test_providers_match_the_mac_and_lmstudio_is_recognised():
    assert [p["id"] for p in aiconfig.PRESETS] == [
        "ollama",
        "lmstudio",
        "anthropic",
        "openai",
        "openrouter",
        "opencode",
        "hermes",
        "custom",
    ]
    assert aiconfig.preset("anthropic")["defaultModel"] == "claude-opus-5-5"
    assert aiconfig.preset("custom")["keyOptional"] and aiconfig.preset("ollama")["keyVariable"] is None
    assert aiconfig.choice_for("lmstudio", "qwen") == {
        "provider": "custom",
        "model": "qwen",
        "baseUrl": "http://localhost:1234/v1",
    }
    assert "model" not in aiconfig.choice_for("lmstudio", None)
    for address in (
        "http://127.0.0.1:1234/v1",
        "http://localhost:1234",
        "http://localhost:1234/v1/",
        "localhost:1234",
    ):
        assert aiconfig.matching({"provider": "custom", "baseUrl": address})["id"] == "lmstudio"
    assert aiconfig.matching({"provider": "custom", "baseUrl": "http://localhost:8000/v1"})["id"] == "custom"


def test_reads_the_ai_check_report():
    line = (
        'AI check: {"make": {"ok": true, "provider": "ollama", "model": "qwen3:8b", "seconds": 17.9}, '
        '"recall": {"ok": false, "provider": "anthropic", "message": "No key for anthropic."}}'
    )
    report = aiconfig.parse_check(line)
    assert report["make"]["ok"] and report["recall"]["message"] == "No key for anthropic."
    assert aiconfig.parse_check("something else") is None
