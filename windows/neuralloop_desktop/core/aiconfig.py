"""The person's AI choices (ai.json, the file the pipeline reads), the providers Settings offers, and the
`--check-ai` report (AIConfig.swift). Keys never live here: they're in Windows Credential Manager."""

import json
from urllib.parse import urlsplit

ENGINES = {
    "auto": "NotebookLM first, my AI whenever it can't",
    "notebooklm": "Only NotebookLM",
    "local": "Only my AI",
}
AUDIO_LENGTHS = ("auto", "short", "default", "long")


def defaults() -> dict:
    return {
        "engine": "auto",
        "make": {"provider": "auto"},
        "tasks": {},
        "recall": {"provider": "ollama", "model": "gemma2:2b"},
        "voices": ["af_heart", "am_michael"],
        "voiceQuality": "fast",
        "audioLength": "auto",
        "hermesTools": False,
    }


def _choice(value) -> dict | None:
    if not isinstance(value, dict) or not isinstance(value.get("provider"), str):
        return None
    out = {"provider": value["provider"]}
    for key in ("model", "baseUrl"):
        if isinstance(value.get(key), str) and value[key]:
            out[key] = value[key]
    return out


def parse(raw) -> dict:
    """Lenient: an odd field keeps its default."""
    d = defaults()
    if not isinstance(raw, dict):
        return d
    if raw.get("engine") in ENGINES:
        d["engine"] = raw["engine"]
    d["make"] = _choice(raw.get("make")) or d["make"]
    if isinstance(raw.get("tasks"), dict):
        d["tasks"] = {k: c for k, v in raw["tasks"].items() if (c := _choice(v))}
    d["recall"] = _choice(raw.get("recall")) or d["recall"]
    voices = raw.get("voices")
    if isinstance(voices, list) and len(voices) == 2 and all(isinstance(v, str) and v for v in voices):
        d["voices"] = voices
    d["voiceQuality"] = "best" if raw.get("voiceQuality") == "best" else "fast"
    if raw.get("audioLength") in AUDIO_LENGTHS:
        d["audioLength"] = raw["audioLength"]
    d["hermesTools"] = raw.get("hermesTools") is True
    return d


def encode(config: dict) -> bytes:
    return json.dumps(parse(config), sort_keys=True, indent=2).encode()


PRESETS = [
    {
        "id": "ollama",
        "title": "Ollama",
        "detail": "Free and private, on this PC. Install Ollama from ollama.com; leave the model empty "
        "to use the one NeuralLoop sets up.",
        "provider": "ollama",
        "keyVariable": None,
        "keyOptional": False,
        "defaultModel": "",
        "baseUrl": None,
        "suggestions": ["qwen3:8b", "qwen3:4b", "gemma2:2b", "gpt-oss:20b"],
    },
    {
        "id": "lmstudio",
        "title": "LM Studio",
        "detail": "Any model you load in LM Studio. Start its local server (Developer → Start Server). Leave "
        "the model empty to use the one that's loaded.",
        "provider": "custom",
        "keyVariable": "NEURALLOOP_API_KEY",
        "keyOptional": True,
        "defaultModel": "",
        "baseUrl": "http://localhost:1234/v1",
        "suggestions": [],
    },
    {
        "id": "anthropic",
        "title": "Claude (Anthropic)",
        "detail": "Your Anthropic API key.",
        "provider": "anthropic",
        "keyVariable": "ANTHROPIC_API_KEY",
        "keyOptional": False,
        "defaultModel": "claude-opus-5-5",
        "baseUrl": None,
        "suggestions": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5"],
    },
    {
        "id": "openai",
        "title": "OpenAI",
        "detail": "Your OpenAI API key.",
        "provider": "openai",
        "keyVariable": "OPENAI_API_KEY",
        "keyOptional": False,
        "defaultModel": "gpt-6-sol",
        "baseUrl": None,
        "suggestions": ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna"],
    },
    {
        "id": "openrouter",
        "title": "OpenRouter",
        "detail": "One key for hundreds of models, including DeepSeek, Qwen, Llama, and Hermes.",
        "provider": "openrouter",
        "keyVariable": "OPENROUTER_API_KEY",
        "keyOptional": False,
        "defaultModel": "deepseek/deepseek-v4.1-flash",
        "baseUrl": None,
        "suggestions": ["deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4-pro-0813"],
    },
    {
        "id": "opencode",
        "title": "opencode",
        "detail": "A model you've connected in opencode (opencode auth login). NeuralLoop runs it without "
        "your own opencode settings, so its tools stay off.",
        "provider": "opencode",
        "keyVariable": None,
        "keyOptional": False,
        "defaultModel": "",
        "baseUrl": None,
        "suggestions": ["deepseek/deepseek-v4-pro", "anthropic/claude-sonnet-5"],
    },
    {
        "id": "hermes",
        "title": "Hermes Agent",
        "detail": "Nous Research's Hermes Agent, as you've set it up. It's an agent: if its tools are on, "
        "text in a book could steer it, so turn its tools off in Hermes first.",
        "provider": "hermes",
        "keyVariable": None,
        "keyOptional": False,
        "defaultModel": "",
        "baseUrl": None,
        "suggestions": [],
    },
    {
        "id": "custom",
        "title": "Any OpenAI-compatible service",
        "detail": "Together, Groq, vLLM, a server of your own: its address, model, and key if it needs one.",
        "provider": "custom",
        "keyVariable": "NEURALLOOP_API_KEY",
        "keyOptional": True,
        "defaultModel": "",
        "baseUrl": None,
        "suggestions": [],
    },
]


def preset(preset_id: str) -> dict | None:
    return next((p for p in PRESETS if p["id"] == preset_id), None)


def is_lmstudio(base_url: str | None) -> bool:
    address = (base_url or "").strip()
    if not address:
        return False
    if "://" not in address:
        address = "http://" + address
    try:
        parts = urlsplit(address)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.hostname in ("localhost", "127.0.0.1")
        and port == 1234
        and parts.path.rstrip("/") in ("", "/v1")
    )


def matching(choice: dict) -> dict | None:
    if choice.get("provider") == "custom":
        return preset("lmstudio") if is_lmstudio(choice.get("baseUrl")) else preset("custom")
    return next((p for p in PRESETS if p["provider"] == choice.get("provider")), None)


def choice_for(preset_id: str, model: str | None, base_url: str | None = None) -> dict:
    p = preset(preset_id) or preset("ollama")
    out = {"provider": p["provider"]}
    chosen = (model or "").strip() or p["defaultModel"]
    if chosen:
        out["model"] = chosen
    address = (base_url or "").strip() or p["baseUrl"]
    if address:
        out["baseUrl"] = address
    return out


def parse_check(line: str) -> dict | None:
    """`AI check: {role: {ok, provider, name, model, seconds} | {ok: false, provider, message}}`."""
    if not line.startswith("AI check: "):
        return None
    try:
        raw = json.loads(line[len("AI check: ") :])
    except ValueError:
        return None
    return raw if isinstance(raw, dict) else None
