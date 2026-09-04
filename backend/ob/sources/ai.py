"""AI services as a source: Claude, ChatGPT, Grok, Gemini, Muse.

One driver, two ways to reach a service:

``cli`` (the default)
    Run the service's own command line tool, which is already signed in
    with the user's account -- ``claude -p`` for Claude (a Pro or Max plan
    works, no API key and no per-request billing), ``gemini -p`` for
    Gemini's free tier, and so on.  Nothing is configured, nothing is
    stored, and the free tier of the account is what gets used.

``api``
    The service's HTTP API with an API key.  The key lives in the system
    keyring (see :mod:`ob.secrets`), never in a file, and the default model
    per service is the small/cheap one -- a paid account only changes which
    model you may put in the *Model* field.

Every mode asks for one strict JSON object and the reply is parsed
defensively (fences, leading prose and trailing chatter are tolerated), so
a chatty model cannot break the panel:

    lookup     {"explanation": "...", "pos": "...", "example": "..."}
    thesaurus  {"groups": [{"meaning", "pos", "synonyms": [], "antonyms": []}]}
    translate  {"translation": "...", "alternatives": [...], "note": "..."}
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from typing import List, Optional, Tuple

from .. import http, languages, paths
from .. import results as R
from .base import Source, SourceError, register

# service id -> (label, default CLI, default API endpoint, fallback model, key hint)
#
# The fallback model is only used when the service's model list cannot be
# read: model ids come and go (a hardcoded one answers 404 the day it is
# retired), so the driver asks the service which models the key may use and
# picks the smallest one - see `list_models` / `pick_model`.
SERVICES = {
    "claude": ("Claude (Anthropic)", "claude -p",
               "https://api.anthropic.com/v1/messages", "claude-sonnet-5",
               "Anthropic API key (only for the API transport)"),
    "chatgpt": ("ChatGPT (OpenAI)", "codex exec",
                "https://api.openai.com/v1/chat/completions", "gpt-4o-mini",
                "OpenAI API key (only for the API transport)"),
    "grok": ("Grok (xAI)", "grok",
             "https://api.x.ai/v1/chat/completions", "grok-4-latest",
             "xAI API key (only for the API transport)"),
    "gemini": ("Gemini (Google)", "gemini -p",
               "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
               "gemini-2.0-flash", "Google AI Studio key (free tier available)"),
    "muse": ("Muse", "muse",
             "", "", "API key of the service"),
}
# Where the service lists the models a key may use, and which of them to
# prefer: the small, cheap ones first (this is a dictionary lookup, not a
# reasoning task).  An empty URL means "same host as the endpoint".
MODEL_LISTS = {
    "claude": "https://api.anthropic.com/v1/models",
    "chatgpt": "https://api.openai.com/v1/models",
    "grok": "https://api.x.ai/v1/models",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
    "muse": "",
}
MODEL_PREFERENCE = {
    "claude": ("haiku", "sonnet"),
    "chatgpt": ("mini", "nano", "turbo"),
    "grok": ("mini", "fast"),
    "gemini": ("flash-lite", "flash"),
    "muse": (),
}
# Ids that are not chat models at all.
_NOT_CHAT = re.compile(r"(?i)(embed|whisper|tts|audio|image|vision-only|dall|moderation|"
                       r"rerank|search|realtime|transcribe|davinci|babbage)")
DEFAULT_SERVICE = "claude"
TRANSPORTS = ("cli", "api")
MAX_TOKENS = 900
CLI_TIMEOUT = float(os.environ.get("OMABABEL_AI_TIMEOUT", "60"))
MODEL_CACHE_TTL = float(os.environ.get("OMABABEL_AI_MODEL_TTL", "86400"))


def service_options() -> List[dict]:
    return [{"value": key, "label": val[0], "command": val[1], "model": val[3]}
            for key, val in SERVICES.items()]


# ------------------------------------------------------------------- models

def auth_headers(service: str, key: str) -> dict:
    """How each service wants its API key (per the services' own docs)."""
    if service == "claude":
        return {"X-Api-Key": key, "anthropic-version": "2023-06-01"}
    if service == "gemini":
        return {"x-goog-api-key": key}
    return {"Authorization": "Bearer " + key}


def _cache_path():
    return paths.cache_dir() / "ai-models.json"


def _cache_read() -> dict:
    try:
        with open(_cache_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _cache_write(data: dict) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        pass


def forget_models(service: str) -> None:
    data = _cache_read()
    if data.pop(service, None) is not None:
        _cache_write(data)


def list_models(service: str, key: str, endpoint: str = "") -> List[str]:
    """Chat model ids this key may use, newest first, cached for a day.

    Model ids are not stable over time – a hardcoded one answers 404 the day
    it is retired – so the service is asked instead of guessed.  A failure
    here is never fatal: the caller falls back to the static default.
    """
    if not key:
        return []
    cached = _cache_read().get(service)
    if isinstance(cached, dict) and time.time() - float(cached.get("ts", 0)) < MODEL_CACHE_TTL:
        return [str(m) for m in cached.get("models", [])]
    url = MODEL_LISTS.get(service) or _models_url_for(endpoint)
    if not url:
        return []
    try:
        data = http.fetch(url, headers=dict(auth_headers(service, key),
                                            **{"Accept": "application/json"}),
                          timeout=15).json()
    except (http.FetchError, ValueError):
        return []
    models = _model_ids(data)
    if models:
        cache = _cache_read()
        cache[service] = {"ts": time.time(), "models": models}
        _cache_write(cache)
    return models


def _models_url_for(endpoint: str) -> str:
    """/v1/models next to an OpenAI-compatible chat endpoint."""
    for tail in ("/chat/completions", "/completions", "/responses"):
        if endpoint.endswith(tail):
            return endpoint[: -len(tail)] + "/models"
    return ""


def _model_ids(data) -> List[str]:
    """Ids out of an Anthropic / OpenAI / Gemini model listing."""
    out: List[str] = []
    if not isinstance(data, dict):
        return out
    rows = data.get("data") if isinstance(data.get("data"), list) else data.get("models")
    for row in rows or []:
        if isinstance(row, str):
            name = row
        elif isinstance(row, dict):
            name = str(row.get("id") or row.get("name") or "")
            methods = row.get("supportedGenerationMethods")
            if isinstance(methods, list) and methods and "generateContent" not in methods:
                continue
        else:
            continue
        name = name.split("/")[-1].strip()      # gemini reports "models/<id>"
        if name and not _NOT_CHAT.search(name):
            out.append(name)
    return out


def pick_model(service: str, models: List[str]) -> str:
    """The smallest useful model of a listing: this is a dictionary lookup,
    not a reasoning task, so cheap and fast wins."""
    for want in MODEL_PREFERENCE.get(service, ()):
        matches = [m for m in models if want in m.lower()]
        if matches:
            # a plain id beats a dated snapshot of the same family
            matches.sort(key=lambda m: (bool(re.search(r"\d{8}$", m)), len(m)))
            return matches[0]
    return models[0] if models else ""


@register
class AI(Source):
    driver = "ai"
    label = "AI service"
    kind = "remote"
    types = ("dictionary", "thesaurus", "translator")
    description = ("Claude, ChatGPT, Grok, Gemini or Muse. Uses the service's signed-in CLI by "
                   "default (a free or paid plan, no API key); an API key can be used instead.")
    default_url = ""
    supports_key = True
    key_hint = "API key – only needed for the API transport"
    translation_modes = ("text",)
    languages = ()          # an AI service answers in any language
    pairs = ()
    order = 61

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.service = str(cfg.get("service") or DEFAULT_SERVICE).lower()
        if self.service not in SERVICES:
            self.service = DEFAULT_SERVICE
        self.transport = str(cfg.get("transport") or "cli").lower()
        if self.transport not in TRANSPORTS:
            self.transport = "cli"
        preset = SERVICES[self.service]
        self.command = str(cfg.get("command") or "").strip() or preset[1]
        # The configured model wins; without one the service is asked which
        # models the key may use (cached), and only if that fails does the
        # static fallback apply.
        self.model_cfg = str(cfg.get("model") or "").strip()
        self.fallback_model = preset[3]
        self._model = self.model_cfg
        # the URL field is an *endpoint override*, and only the API transport
        # has an endpoint at all
        override = self.url if (self.transport == "api" and self.url.startswith("http")) else ""
        self.endpoint = override or preset[2]

    @staticmethod
    def services() -> List[dict]:
        """Service presets for the preferences panel."""
        return service_options()

    @property
    def model(self) -> str:
        """The model to send.  Resolved once per process, and only for the
        API transport – a CLI uses whatever its own configuration says."""
        if self._model:
            return self._model
        if self.transport != "api":
            return ""
        self._model = pick_model(self.service, list_models(self.service, self.api_key, self.endpoint)) \
            or self.fallback_model
        return self._model

    def describe(self) -> dict:
        out = super().describe()
        out.update({"service": self.service, "transport": self.transport,
                    "model": self._model or (self.model_cfg or (self.fallback_model
                                                                if self.transport == "api" else ""))})
        return out

    # -------------------------------------------------------------- modes
    def lookup(self, word: str, lang: str) -> dict:
        word = word.strip()
        if not word:
            return {"entries": [], "url": ""}
        data = self._ask(
            f"Explain the {languages.name(lang)} word or phrase \"{word}\" for a dictionary entry.",
            'Answer with one JSON object and nothing else: {"explanation": "one succinct '
            'explanation, at most two sentences, in ' + languages.name(lang) + '", '
            '"pos": "part of speech or empty", "example": "one short example sentence or empty"}')
        explanation = R.clean(data.get("explanation", ""))
        if not explanation:
            return {"entries": [], "url": ""}
        examples = [e for e in [R.clean(data.get("example", ""))] if e]
        entry = R.entry(word, pos=R.clean(data.get("pos", "")),
                        senses=[R.sense(explanation, examples=examples)],
                        lang=lang, extra={"model": self.model})
        return {"entries": [entry], "url": ""}

    def thesaurus(self, word: str, lang: str) -> dict:
        word = word.strip()
        if not word:
            return R.thesaurus([], [])
        data = self._ask(
            f"Give synonyms and antonyms of the {languages.name(lang)} word \"{word}\", "
            "grouped by meaning.",
            'Answer with one JSON object and nothing else: {"groups": [{"meaning": "a short '
            'label for this meaning", "pos": "part of speech or empty", "synonyms": ["…"], '
            '"antonyms": ["…"]}]}. Use at most 5 groups and at most 12 words per list, '
            'single words or short phrases only, in ' + languages.name(lang) + '.')
        groups = []
        for g in data.get("groups") or []:
            if not isinstance(g, dict):
                continue
            groups.append(R.group(_words(g.get("synonyms")), _words(g.get("antonyms")),
                                  label=R.clean(g.get("meaning", "")), pos=R.clean(g.get("pos", ""))))
        if not groups:
            groups = [R.group(_words(data.get("synonyms")), _words(data.get("antonyms")))]
        return R.thesaurus([], [], groups=groups)

    def translate(self, text: str, src: str, dst: str) -> dict:
        text = text.strip()
        if not text:
            return R.translation("text")
        data = self._ask(
            f"Translate from {languages.name(src)} to {languages.name(dst)}, preserving the "
            f"meaning, register and tone rather than the wording:\n\n{text}",
            'Answer with one JSON object and nothing else: {"translation": "the best '
            'meaning-preserving translation", "alternatives": ["at most 3 other renderings"], '
            '"note": "a short note about an ambiguity, or empty"}')
        translation = R.clean(data.get("translation", ""))
        if not translation:
            raise SourceError(f"{self.name}: no translation in the reply")
        alts = [R.clean(a) for a in (data.get("alternatives") or []) if R.clean(a)]
        note = R.clean(data.get("note", ""))
        if note:
            alts.append(note)
        return R.translation("text", text=translation, alternatives=alts[:4])

    # ------------------------------------------------------------- engine
    def _ask(self, task: str, shape: str) -> dict:
        prompt = (task + "\n\n" + shape
                  + "\n\nNo markdown, no code fence, no explanation outside the JSON.")
        raw = self._api_call(prompt) if self.transport == "api" else self._cli_call(prompt)
        data = parse_json(raw)
        if data is None:
            raise SourceError(f"{self.name}: the reply was not JSON ({_snippet(raw)})")
        return data

    # -- CLI: the signed-in tool of the service (free or paid plan)
    def _cli_call(self, prompt: str) -> str:
        if os.environ.get("OMABABEL_OFFLINE"):
            raise SourceError("offline mode")
        argv = _split_command(self.command)
        if not argv:
            raise SourceError(f"{self.name}: no command configured")
        binary = shutil.which(argv[0])
        if not binary:
            raise SourceError(f"{self.name}: '{argv[0]}' is not installed – install the "
                              f"{SERVICES[self.service][0]} CLI and sign in, or switch the "
                              "source to the API transport")
        try:
            proc = subprocess.run([binary] + argv[1:], input=prompt, capture_output=True,
                                  text=True, timeout=CLI_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise SourceError(f"{self.name}: '{argv[0]}' timed out after {int(CLI_TIMEOUT)}s")
        except OSError as e:
            raise SourceError(f"{self.name}: {e}")
        if proc.returncode != 0:
            raise SourceError(f"{self.name}: {_snippet(proc.stderr or proc.stdout) or 'command failed'}")
        return proc.stdout or ""

    # -- API: the service's HTTP endpoint with a key from the keyring
    def _api_call(self, prompt: str, retried: bool = False) -> str:
        if not self.api_key:
            raise SourceError(f"{self.name}: the API transport needs a key (Preferences → the "
                              "source → API key), or switch back to the CLI transport")
        if not self.endpoint:
            raise SourceError(f"{self.name}: no API endpoint configured for this service")
        model = self.model
        endpoint = self.endpoint.replace("{model}", model)
        body, headers, pick = self._request_for(prompt, model)
        try:
            resp = http.fetch(endpoint, json_body=body, headers=headers, method="POST",
                              timeout=CLI_TIMEOUT)
            data = resp.json()
        except http.FetchError as e:
            if e.status in (401, 403):
                raise SourceError(f"{self.name}: the API rejected the key")
            if e.status == 429:
                raise SourceError(f"{self.name}: rate limited by the service")
            if e.status == 404:
                # An id that was fine yesterday is gone today: forget what was
                # cached, ask the service again and try once more.
                if not retried and not self.model_cfg:
                    forget_models(self.service)
                    self._model = ""
                    if self.model != model:
                        return self._api_call(prompt, retried=True)
                available = list_models(self.service, self.api_key, self.endpoint)
                hint = ("; this key can use " + ", ".join(available[:6])) if available else ""
                raise SourceError(f"{self.name}: the service does not know the model "
                                  f"'{model}'{hint}")
            raise SourceError(f"{self.name}: {e}")
        except ValueError:
            raise SourceError(f"{self.name}: invalid JSON from the API")
        try:
            return pick(data)
        except (KeyError, IndexError, TypeError):
            raise SourceError(f"{self.name}: unexpected API reply ({_snippet(json.dumps(data))})")

    def _request_for(self, prompt: str, model: str) -> Tuple[dict, dict, object]:
        """(body, headers, extractor) for the service's API flavour."""
        if self.service == "claude":
            # https://platform.claude.com/docs/en/api – the Messages API takes
            # the key in X-Api-Key next to the (required) version header, and
            # model/max_tokens/messages are all mandatory.
            return ({"model": model, "max_tokens": MAX_TOKENS,
                     "messages": [{"role": "user", "content": prompt}]},
                    dict(auth_headers("claude", self.api_key),
                         **{"Accept": "application/json", "Content-Type": "application/json"}),
                    lambda d: "".join(part.get("text", "") for part in d["content"]
                                      if part.get("type", "text") == "text"))
        if self.service == "gemini":
            return ({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                     "generationConfig": {"maxOutputTokens": MAX_TOKENS}},
                    dict(auth_headers("gemini", self.api_key),
                         **{"Accept": "application/json", "Content-Type": "application/json"}),
                    lambda d: "".join(p.get("text", "")
                                      for p in d["candidates"][0]["content"]["parts"]))
        # OpenAI-compatible (ChatGPT, Grok, Muse and anything else that speaks it)
        return ({"model": model, "max_completion_tokens": MAX_TOKENS,
                 "messages": [{"role": "user", "content": prompt}]},
                dict(auth_headers(self.service, self.api_key),
                     **{"Accept": "application/json", "Content-Type": "application/json"}),
                lambda d: d["choices"][0]["message"]["content"])


def _words(value) -> List[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [R.clean(w) for w in value if isinstance(w, str) and R.clean(w)]


def _split_command(command: str) -> List[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _snippet(text: str, limit: int = 120) -> str:
    text = " ".join(str(text or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(raw: str) -> Optional[dict]:
    """The first JSON object in a model's reply.

    Models wrap their answer in fences, prefix it with "Here you go:" or
    append a closing remark; a CLI may print a banner first.  Braces inside
    strings are handled, so a nested object never truncates the match.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    for candidate in [text] + [m.group(1) for m in _FENCE.finditer(text)]:
        candidate = candidate.strip()
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    start = -1
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    data = json.loads(text[start:i + 1])
                except ValueError:
                    start = -1
                    continue
                if isinstance(data, dict):
                    return data
                start = -1
    return None
