"""Small, standard-library preferences store for Codex Dictation."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from runtime_paths import ROOT


DEFAULTS: dict[str, Any] = {
    "microphone": "",
    "hotkey": "Ctrl+Alt+Space",
    "hotkey_mode": "toggle",
    "auto_paste": False,
    "warmup": True,
    "idle_seconds": 30,
    "tail_seconds": 0.7,
    "max_record_seconds": 120,
    "dictionary_enabled": False,
    "dictionary": [],
    "topmost": False,
    "minimize_to_tray": False,
    "language": "pt-BR",
}

MAX_RULES = 100
MAX_RULE_TEXT = 256


def _valid_rules(value: Any) -> list[dict[str, str]] | None:
    if not isinstance(value, list) or len(value) > MAX_RULES:
        return None
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"from", "to"}:
            return None
        source, target = item["from"], item["to"]
        if not isinstance(source, str) or not isinstance(target, str):
            return None
        if not source.strip() or len(source) > MAX_RULE_TEXT or len(target) > MAX_RULE_TEXT:
            return None
        key = source.casefold()
        if key in seen:
            return None
        seen.add(key)
        result.append({"from": source, "to": target})
    return result


def _validated(data: Any) -> dict[str, Any]:
    result = dict(DEFAULTS)
    if not isinstance(data, dict):
        return result
    string_fields = ("microphone", "hotkey")
    bool_fields = ("auto_paste", "warmup", "dictionary_enabled", "topmost", "minimize_to_tray")
    for key in string_fields:
        value = data.get(key)
        if isinstance(value, str) and len(value) <= 256:
            result[key] = value
    language = data.get("language")
    if language in ("pt-BR", "en"):
        result["language"] = language
    for key in bool_fields:
        value = data.get(key)
        if type(value) is bool:
            result[key] = value
    mode = data.get("hotkey_mode")
    if mode in ("toggle", "hold") and isinstance(mode, str):
        result["hotkey_mode"] = mode
    for key, low, high, kind in (
        ("idle_seconds", 10, 120, int),
        ("max_record_seconds", 15, 120, int),
        ("tail_seconds", 0.5, 2.0, (int, float)),
    ):
        value = data.get(key)
        if isinstance(value, kind) and not isinstance(value, bool) and low <= value <= high:
            result[key] = float(value) if key == "tail_seconds" else value
    rules = _valid_rules(data.get("dictionary"))
    if rules is not None:
        result["dictionary"] = rules
    return result


class SettingsStore:
    """Load and atomically save validated preferences. ``path`` names the JSON file."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        self.path = Path(path) if path is not None else ROOT / "userdata" / "settings.json"
        self.load_warning: str | None = None

    def load(self) -> dict[str, Any]:
        self.load_warning = None
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
        except FileNotFoundError:
            return dict(DEFAULTS)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            # Leave the user's file untouched; callers can surface this without logging its contents.
            self.load_warning = f"Preferências inválidas ou indisponíveis: {type(exc).__name__}."
            return dict(DEFAULTS)
        return _validated(data)

    def save(self, settings: dict[str, Any]) -> dict[str, Any]:
        clean = _validated(settings)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(clean, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        return clean


def apply_dictionary(text: str, rules: list[dict[str, str]], enabled: bool) -> str:
    """Apply literal, whole-word/phrase replacements in one non-cascading pass."""
    if not enabled or not isinstance(text, str):
        return text
    safe = _valid_rules(rules)
    if not safe:
        return text
    # Alternatives are ordered longest-first so overlapping phrases prefer the longer rule.
    ordered = sorted(safe, key=lambda rule: len(rule["from"]), reverse=True)
    alternatives = "|".join(re.escape(rule["from"]) for rule in ordered)
    pattern = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE | re.UNICODE)
    replacements = {rule["from"].casefold(): rule["to"] for rule in ordered}
    return pattern.sub(lambda match: replacements[match.group(0).casefold()], text)


def parse_dictionary(text: str) -> list[dict[str, str]]:
    """Parse one ``original = replacement`` rule per line, raising a pt-BR error on invalid input."""
    rules: list[dict[str, str]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if "=" not in line:
            raise ValueError(f"Linha {line_number}: use o formato 'original = substituição'.")
        source, target = (part.strip() for part in line.split("=", 1))
        if not source or not target:
            raise ValueError(f"Linha {line_number}: origem e substituição precisam ter conteúdo.")
        if len(source) > MAX_RULE_TEXT or len(target) > MAX_RULE_TEXT:
            raise ValueError(f"Linha {line_number}: cada campo pode ter no máximo {MAX_RULE_TEXT} caracteres.")
        if source.casefold() in seen:
            raise ValueError(f"Linha {line_number}: origem duplicada.")
        seen.add(source.casefold())
        rules.append({"from": source, "to": target})
        if len(rules) > MAX_RULES:
            raise ValueError(f"O dicionário pode ter no máximo {MAX_RULES} regras.")
    return rules


def format_dictionary(rules: list[dict[str, str]]) -> str:
    safe = _valid_rules(rules)
    if safe is None:
        raise ValueError("Regras inválidas: verifique campos, limites e origens duplicadas.")
    return "\n".join(f"{rule['from']} = {rule['to']}" for rule in safe)
