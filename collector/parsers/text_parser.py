from __future__ import annotations


def detect(line: str) -> bool:
    return True  # fallback for any format we do not recognize


def parse(line: str) -> dict:
    return {"kind": "log", "ts": None, "host": "unknown", "message": line, "format": "text"}
