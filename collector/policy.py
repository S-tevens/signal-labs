"""Data policy ("markings"): load, validate and enforce collector/policy.yaml.

Fail closed: if the policy cannot be satisfied the payload is blocked, not sent.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .redact import RULE_NAMES
from .schema import Payload

CLASSIFICATIONS = {"ALLOWED_METADATA", "PSEUDONYMIZED", "DERIVED_SUMMARY", "LOCAL_ONLY"}
_OPTIONAL_BODY = ("metric", "event")
_SPEC_KEYS = {"classification", "treatment", "required"}
_SCHEMA_REQUIRED = frozenset(n for n, f in Payload.model_fields.items() if f.is_required())


class PolicyError(ValueError):
    """The policy file is invalid. The collector refuses to start rather than guess."""


@dataclass(frozen=True)
class Decision:
    payload: dict | None  # the policy-compliant payload, or None if blocked
    violations: list[str]

    @property
    def blocked(self) -> bool:
        return self.payload is None


class Policy:
    def __init__(self, data: dict):
        try:
            self.version = int(data["version"])
            self.fields: dict[str, dict] = dict(data["fields"])
            self.metrics: list[str] = list(data["metrics"])
            self.event_categories: list[str] = list(data["event_categories"])
            self.local_only: dict[str, dict] = dict(data.get("local_only", {}))
            self.redaction_rules: list[str] = list(data.get("redaction_rules", []))
            self.classifications: dict[str, str] = dict(data.get("classifications", {}))
        except (KeyError, TypeError, ValueError) as exc:
            raise PolicyError(f"malformed policy: {exc!r}") from exc
        self._validate()

    @classmethod
    def load(cls, path: str | Path) -> "Policy":
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise PolicyError(f"cannot read policy {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise PolicyError("policy must be a mapping")
        return cls(data)

    def _validate(self) -> None:
        if not self.fields:
            raise PolicyError("fields must not be empty")
        for group in (self.fields, self.local_only):
            for name, spec in group.items():
                extra = set(spec or {}) - _SPEC_KEYS
                if extra:
                    raise PolicyError(f"{name!r} has unknown keys {sorted(extra)} (a comma in an unquoted value?)")
        for name, spec in self.fields.items():
            cls_ = (spec or {}).get("classification")
            if cls_ not in CLASSIFICATIONS:
                raise PolicyError(f"field {name!r} has unknown classification {cls_!r}")
            if cls_ == "LOCAL_ONLY":
                raise PolicyError(f"field {name!r} is LOCAL_ONLY, so it cannot be an egress field")
        for name, spec in self.local_only.items():
            if (spec or {}).get("classification") != "LOCAL_ONLY":
                raise PolicyError(f"local_only entry {name!r} must be classified LOCAL_ONLY")
            if name in self.fields:
                raise PolicyError(f"{name!r} is both an egress field and local-only")
        unknown = [r for r in self.redaction_rules if r not in RULE_NAMES]
        if unknown:
            raise PolicyError(f"unknown redaction rules: {unknown}")

    def apply(self, payload: dict) -> Decision:
        """Strip fields the policy does not list, then check the body is allowed. Block if it cannot comply."""
        violations: list[str] = []
        kept = {k: v for k, v in payload.items() if k in self.fields}
        for extra in sorted(set(payload) - set(self.fields)):
            violations.append(f"field not in policy removed: {extra}")

        # Required means required by the payload schema (what the SaaS will insist on), not merely listed here.
        # If the policy forbids a field the payload cannot do without, the payload cannot comply: block it.
        for name in sorted(_SCHEMA_REQUIRED):
            if name not in kept:
                violations.append(f"required field not allowed by policy: {name}")
                return Decision(None, violations)

        metric, event = kept.get("metric"), kept.get("event")
        if metric is None and event is None:
            violations.append("no metric or event is allowed by policy")
            return Decision(None, violations)
        if metric is not None and metric.get("name") not in self.metrics:
            violations.append(f"metric not allowed by policy: {metric.get('name')}")
            return Decision(None, violations)
        if event is not None and event.get("category") not in self.event_categories:
            violations.append(f"event category not allowed by policy: {event.get('category')}")
            return Decision(None, violations)
        return Decision(kept, violations)

    def describe(self) -> dict:
        """What the egress panel shows: every field and its marking, and what stays local."""
        return {
            "version": self.version,
            "classifications": self.classifications,
            "egress_fields": {
                name: {
                    "classification": spec["classification"],
                    "treatment": spec.get("treatment", ""),
                    "required": spec.get("required", name not in _OPTIONAL_BODY),
                }
                for name, spec in self.fields.items()
            },
            "metrics": self.metrics,
            "event_categories": self.event_categories,
            "local_only": {name: spec.get("treatment", "") for name, spec in self.local_only.items()},
            "redaction_rules": self.redaction_rules,
        }
