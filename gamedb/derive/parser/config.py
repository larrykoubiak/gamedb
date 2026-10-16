"""Load and validate the declarative archive-name format definitions."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re


REFERENCE_DIRECTORY = Path(__file__).resolve().parents[3] / "data" / "reference"
FORMAT_PATH = REFERENCE_DIRECTORY / "source_formats.json"
VOCABULARY_PATH = REFERENCE_DIRECTORY / "tag_vocabulary.json"


def _load_json(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    return json.loads(raw), raw


def _resolve_inheritance(collections: dict) -> dict:
    resolved = {}
    resolving = set()

    def resolve(name):
        if name in resolved:
            return resolved[name]
        if name in resolving:
            raise ValueError(f"archive format inheritance cycle at {name!r}")
        if name not in collections:
            raise ValueError(f"unknown inherited archive format {name!r}")
        resolving.add(name)
        value = deepcopy(collections[name])
        parent = value.pop("inherits", None)
        if parent:
            inherited = deepcopy(resolve(parent))
            inherited.update(value)
            value = inherited
        resolving.remove(name)
        resolved[name] = value
        return value

    for collection in collections:
        resolve(collection)
    return resolved


def _compile_rule(rule: dict, context: str) -> dict:
    value = deepcopy(rule)
    pattern = value.get("pattern")
    if pattern is not None:
        flags = re.IGNORECASE if value.pop("ignore_case", False) else 0
        try:
            value["regex"] = re.compile(pattern, flags)
        except re.error as error:
            raise ValueError(f"invalid regex in {context}: {error}") from error
    return value


def _load_formats() -> tuple[dict, dict, str]:
    document, format_bytes = _load_json(FORMAT_PATH)
    vocabulary, vocabulary_bytes = _load_json(VOCABULARY_PATH)
    if document.get("version") != 1:
        raise ValueError("unsupported source_formats.json version")
    collections = _resolve_inheritance(document.get("collections", {}))
    if not collections:
        raise ValueError("source_formats.json defines no collections")

    for name, profile in collections.items():
        if profile.get("dat_identity") not in {
            "english_translations", "name_components", "path_components",
        }:
            raise ValueError(f"{name} has an unknown DAT identity strategy")
        boundary = profile.get("boundary", {})
        if boundary.get("kind") == "region":
            vocabulary_name = boundary.get("vocabulary")
            if vocabulary_name not in vocabulary or not isinstance(vocabulary[vocabulary_name], dict):
                raise ValueError(f"{name} refers to unknown region vocabulary {vocabulary_name!r}")
            boundary["values"] = frozenset(vocabulary[vocabulary_name])
            boundary["fallback_values"] = frozenset(boundary.get("additional_values", []))
        elif boundary.get("kind") == "sequence":
            groups = boundary.get("groups", [])
            if not groups:
                raise ValueError(f"{name} has an empty boundary sequence")
            boundary["groups"] = [
                _compile_rule(group, f"{name}.boundary.groups") for group in groups
            ]
        else:
            raise ValueError(f"{name} has an unknown boundary kind")
        profile["prefix_tags"] = [
            _compile_rule(rule, f"{name}.prefix_tags")
            for rule in profile.get("prefix_tags", [])
        ]

    digest = hashlib.sha256(format_bytes + b"\0" + vocabulary_bytes).hexdigest()[:12]
    return collections, vocabulary, f"1:{digest}"


FORMATS, VOCABULARY, FORMAT_VERSION = _load_formats()
COLLECTIONS = frozenset(FORMATS)
