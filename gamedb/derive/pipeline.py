"""Ordered execution of the derivation-owned data contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

import yaml
from sqlalchemy.engine import Engine

from .extractors.archive_path_extract import ArchivePathExtractor
from .extractors.dat_extract import DatExtractor
from .extractors.inventory_extract import InventoryExtractor
from .extractors.name_derivation import NameDerivation
from .extractors.reference_extract import ReferenceExtractor
from .extractors.release_assemble import ReleaseAssembler
from .extractors.system_extract import SystemExtractor
from .extractors.translation_member_title_extract import TranslationMemberTitleExtractor
from .schema_manager import DerivedSchemaManager


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIRECTORY = PROJECT_ROOT / "reference"


@dataclass(frozen=True)
class DerivationLayer:
    name: str
    description: str
    extractor: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]


class DerivationPipeline:
    """Run explicit extractors; no layer infers hidden upstream work."""

    def __init__(
        self, engine: Engine | None, manifest: Path = PROJECT_ROOT / "derive.yml"
    ):
        self.engine = engine
        document = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        self.name = document["name"]
        self.layers = tuple(
            DerivationLayer(
                value["name"], value["description"], value["extractor"],
                tuple(value.get("reads", [])), tuple(value.get("writes", [])),
            )
            for value in document["layers"]
        )
        self._executors = {
            "schema_manager": self._schema,
            "reference_extract": self._reference,
            "dat_extract": self._dat,
            "system_extract": self._system,
            "inventory_extract": self._inventory,
            "translation_member_title_extract": self._translation_member_titles,
            "archive_path_extract": self._paths,
            "archive_name_extract": self._names,
            "release_assemble": self._releases,
        }
        unknown = {
            layer.extractor for layer in self.layers
            if layer.extractor not in self._executors
        }
        if unknown:
            raise ValueError(f"unknown derivation extractor(s): {sorted(unknown)}")

    @property
    def layer_names(self) -> tuple[str, ...]:
        return tuple(layer.name for layer in self.layers)

    def select(
        self, exact: tuple[str, ...] = (), from_layer: str | None = None
    ) -> tuple[DerivationLayer, ...]:
        unknown = (set(exact) | ({from_layer} if from_layer else set())) - set(self.layer_names)
        if unknown:
            raise ValueError(f"unknown derivation layer(s): {', '.join(sorted(unknown))}")
        if exact and from_layer:
            raise ValueError("exact layers cannot be combined with --from-layer")
        if exact:
            requested = set(exact)
            return tuple(layer for layer in self.layers if layer.name in requested)
        start = self.layer_names.index(from_layer) if from_layer else 0
        return self.layers[start:]

    def describe(self, layers: tuple[DerivationLayer, ...] | None = None) -> str:
        selected = layers or self.layers
        lines = [f"Derivation pipeline: {self.name}"]
        for layer in selected:
            lines.extend((
                "",
                f"{layer.name}: {layer.description}",
                f"  extractor: {layer.extractor}",
                f"  reads: {', '.join(layer.reads)}",
                f"  writes: {', '.join(layer.writes)}",
            ))
        return "\n".join(lines)

    def execute(self, layers: tuple[DerivationLayer, ...] | None = None) -> None:
        if self.engine is None:
            raise RuntimeError("database engine is required to execute derivation")
        selected = layers or self.layers
        for index, layer in enumerate(selected, 1):
            started = time.monotonic()
            print(f"[{index}/{len(selected)}] {layer.name}: {layer.description}", flush=True)
            result = self._executors[layer.extractor]()
            elapsed = int(time.monotonic() - started)
            suffix = f" {result}" if result is not None else ""
            print(f"[{index}/{len(selected)}] {layer.name} finished ({elapsed}s){suffix}", flush=True)

    def _schema(self):
        DerivedSchemaManager(self.engine).reset()

    def _reference(self):
        with self.engine.begin() as connection:
            ReferenceExtractor(REFERENCE_DIRECTORY).execute(connection)

    def _dat(self):
        with self.engine.begin() as connection:
            return f"rows={DatExtractor().execute(connection):,}"

    def _system(self):
        with self.engine.begin() as connection:
            return f"rows={SystemExtractor().execute(connection):,}"

    def _inventory(self):
        with self.engine.begin() as connection:
            InventoryExtractor().execute(connection)

    def _translation_member_titles(self):
        with self.engine.begin() as connection:
            count = TranslationMemberTitleExtractor().execute(connection)
            return f"rows={count:,}"

    def _paths(self):
        with self.engine.begin() as connection:
            ArchivePathExtractor().execute(connection)

    def _names(self):
        return NameDerivation().execute(self.engine)

    def _releases(self):
        return ReleaseAssembler().execute(self.engine)
