"""AI engine: a Gemini-written investigation summary for an incident, built from metadata only.

The detectors (thresholds, rolling statistics, correlation) decide WHAT is an incident. This engine explains one in plain
language for the on-call engineer: what happened, why it was flagged, what to check first and what is uncertain.

Privacy: the SaaS only ever holds allow-listed metadata, and the model is given a further-reduced subset of it (the
fields in ALLOWED_SIGNAL_FIELDS plus the platform's own suggestion). It never sees raw logs, hostnames, source
or collector IDs, or payload IDs. The call happens on demand when someone opens an incident, never on the ingest path.

Safety: no key, a timeout, an error or a rate limit all return {"available": False, ...} and the rule-based
recommendation stays the source of truth. The key is read from GEMINI_API_KEY or the git-ignored file data/gemini.key,
sent only in a request header, and never logged or returned.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import httpx

log = logging.getLogger("saas.llm")

PROVIDER = "Google Gemini"
MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
KEY_FILE = Path(os.getenv("GEMINI_API_KEY_FILE") or Path(__file__).resolve().parents[1] / "data" / "gemini.key")

# The only incident fields the model may see.
ALLOWED_SIGNAL_FIELDS = ("signal", "value", "unit", "method", "baseline", "robust_z", "samples", "persistence_windows", "severity", "why")
ALLOWED_RECOMMENDATION_FIELDS = ("action", "likely_cause", "why", "confidence", "confidence_type")

SYSTEM_PROMPT = (
    "You help an on-call engineer understand an infrastructure incident. You are given ONLY metadata: detector signals with "
    "their values, the detection method, thresholds or baselines, and a rule-based suggestion. You never see raw logs. "
    "Write plain text, at most 120 words, in four short parts labelled 'What happened:', 'Why it was flagged:', "
    "'Check first:' (two or three concrete investigation steps) and 'Uncertain:'. Cite the actual numbers from the data. "
    "Use the word 'possible' for causes: you cannot prove a root cause. Do not invent facts that are not in the data, "
    "and do not suggest running commands or changing systems."
)


def load_key() -> str | None:
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if key:
        return key
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def build_facts(props: dict) -> dict:
    """Reduce an incident to what the model may see. Anything not named here is dropped."""
    signals = []
    for s in (props.get("signals") or [])[:8]:
        signals.append({k: s[k] for k in ALLOWED_SIGNAL_FIELDS if k in s and isinstance(s[k], (str, int, float, bool))})
    rec = props.get("recommendation")
    rec = rec if isinstance(rec, dict) else {}
    return {
        "severity": props.get("severity"),
        "alerts_in_incident": props.get("alert_count"),
        "first_event_utc": props.get("first_ts"),
        "last_event_utc": props.get("last_ts"),
        "signals": signals,
        "rule_based_suggestion": {k: rec[k] for k in ALLOWED_RECOMMENDATION_FIELDS if k in rec and isinstance(rec[k], (str, int, float))},
    }


class Engine:
    def __init__(self, key: str | None = None, client: httpx.Client | None = None, model: str = MODEL,
                 timeout: float = 15.0, max_per_minute: int = 20, cache_size: int = 256):
        self._key = key
        self._client = client
        self.model, self.timeout, self.max_per_minute = model, timeout, max_per_minute
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._cache_size = cache_size
        self._calls: list[float] = []
        self._lock = threading.Lock()

    def key(self) -> str | None:
        return self._key or load_key()

    def status(self) -> dict:
        return {"available": bool(self.key()), "provider": PROVIDER, "model": self.model,
                "sends": "incident metadata only (no raw logs, hostnames or IDs)"}

    def explain(self, props: dict) -> dict:
        key = self.key()
        if not key:
            return {"available": False, "reason": "No Gemini API key is configured on the platform."}
        facts = build_facts(props)
        if not facts["signals"]:
            return {"available": False, "reason": "This incident has no retained signals to explain."}
        digest = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()
        with self._lock:
            if digest in self._cache:
                self._cache.move_to_end(digest)
                return {**self._cache[digest], "cached": True}
            now = time.time()
            self._calls = [t for t in self._calls if now - t < 60]
            if len(self._calls) >= self.max_per_minute:
                return {"available": False, "reason": "The AI summary rate limit was reached; try again in a minute."}
            self._calls.append(now)
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": "Incident metadata (JSON):\n" + json.dumps(facts, indent=1)}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500},
        }
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            resp = client.post(ENDPOINT.format(model=self.model), json=body, headers={"x-goog-api-key": key, "Content-Type": "application/json"})
            resp.raise_for_status()
            parts = resp.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        except httpx.HTTPStatusError as exc:
            log.warning("Gemini request failed: HTTP %s", exc.response.status_code)
            return {"available": False, "reason": f"The AI service returned HTTP {exc.response.status_code}."}
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            log.warning("Gemini request failed: %s", type(exc).__name__)
            return {"available": False, "reason": "The AI service could not be reached or returned an unexpected answer."}
        finally:
            if self._client is None:
                client.close()
        if not text:
            return {"available": False, "reason": "The AI service returned no text."}
        result = {
            "available": True, "text": text[:1500], "provider": PROVIDER, "model": self.model,
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "input_digest": digest[:16],
            "basis": "Generated from incident metadata only. It is an investigation lead, not proof of a root cause.",
        }
        with self._lock:
            self._cache[digest] = result
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return {**result, "cached": False}
