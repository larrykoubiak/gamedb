"""Load and validate the declarative catalog workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class StepConfig:
    """One executable operation within a layer."""

    name: str
    type: str
    files: tuple[Path, ...] = ()


@dataclass(frozen=True)
class LayerConfig:
    """A named, selectable group of ordered workflow steps."""

    name: str
    description: str
    steps: tuple[StepConfig, ...]


@dataclass(frozen=True)
class WorkflowConfig:
    """Validated workflow definition resolved relative to its YAML file."""

    name: str
    root: Path
    layers: tuple[LayerConfig, ...]

    @classmethod
    def load(cls, path: str | Path) -> "WorkflowConfig":
        config_path = Path(path).resolve()
        if not config_path.is_file():
            raise FileNotFoundError(f"Pipeline file not found: {config_path}")
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Pipeline must contain a YAML mapping: {config_path}")

        name = _required_text(raw, "name", "pipeline")
        raw_layers = raw.get("layers")
        if not isinstance(raw_layers, list) or not raw_layers:
            raise ValueError("Pipeline requires a non-empty layers list")

        root = config_path.parent
        layers = tuple(_load_layer(value, root) for value in raw_layers)
        _require_unique((layer.name for layer in layers), "layer")
        _require_unique(
            (step.name for layer in layers for step in layer.steps), "step"
        )
        return cls(name=name, root=root, layers=layers)

    @property
    def layer_names(self) -> tuple[str, ...]:
        return tuple(layer.name for layer in self.layers)

    def select(
        self,
        layers: tuple[str, ...] = (),
        from_layer: str | None = None,
        through_layer: str | None = None,
    ) -> "WorkflowConfig":
        """Select exact layers or one inclusive ordered range."""
        if layers and (from_layer or through_layer):
            raise ValueError("Exact layers cannot be combined with a layer range")
        known = self.layer_names
        requested = set(layers)
        if from_layer:
            requested.add(from_layer)
        if through_layer:
            requested.add(through_layer)
        unknown = sorted(requested - set(known))
        if unknown:
            raise ValueError(f"Unknown pipeline layer(s): {', '.join(unknown)}")

        if layers:
            chosen = tuple(layer for layer in self.layers if layer.name in set(layers))
        else:
            start = known.index(from_layer) if from_layer else 0
            end = known.index(through_layer) + 1 if through_layer else len(known)
            if start >= end:
                raise ValueError("The starting layer must precede the ending layer")
            chosen = self.layers[start:end]
        if not chosen:
            raise ValueError("Layer selection is empty")
        return WorkflowConfig(self.name, self.root, chosen)


def _load_layer(raw: object, root: Path) -> LayerConfig:
    if not isinstance(raw, dict):
        raise ValueError("Each pipeline layer must be a YAML mapping")
    name = _required_text(raw, "name", "layer")
    description = _required_text(raw, "description", f"layer {name}")
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError(f"Layer {name} requires a non-empty steps list")
    return LayerConfig(
        name=name,
        description=description,
        steps=tuple(_load_step(value, root) for value in raw_steps),
    )


def _load_step(raw: object, root: Path) -> StepConfig:
    if not isinstance(raw, dict):
        raise ValueError("Each pipeline step must be a YAML mapping")
    name = _required_text(raw, "name", "step")
    step_type = _required_text(raw, "type", f"step {name}")
    if step_type == "run_sql":
        raw_files = raw.get("files")
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError(f"run_sql step {name} requires a non-empty files list")
        files = tuple(_resolve_file(root, value, name) for value in raw_files)
        return StepConfig(name=name, type=step_type, files=files)
    if step_type == "build_media":
        if raw.get("files") is not None:
            raise ValueError(f"build_media step {name} does not accept files")
        return StepConfig(name=name, type=step_type)
    raise ValueError(f"Step {name} has unsupported type: {step_type}")


def _required_text(raw: dict, key: str, context: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} requires a non-empty {key}")
    return value.strip()


def _resolve_file(root: Path, value: object, step_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Step {step_name} requires a file path")
    path = (root / value).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Step {step_name} file not found: {path}")
    return path


def _require_unique(values, label: str) -> None:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"Duplicate pipeline {label}(s): {', '.join(sorted(duplicates))}")
