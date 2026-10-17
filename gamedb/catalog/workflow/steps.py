"""Concrete executable roles used by the catalog workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import time

from .config import StepConfig


@dataclass(frozen=True)
class WorkflowContext:
    """Shared execution context for every workflow step."""

    project_root: Path


class WorkflowStep:
    """Base contract for a configured rebuild operation."""

    def __init__(self, name: str):
        self.name = name

    def execute(self, context: WorkflowContext) -> None:
        raise NotImplementedError


class RunSqlStep(WorkflowStep):
    """Execute one atomic ordered batch of psql files."""

    def __init__(self, name: str, files: tuple[Path, ...]):
        super().__init__(name)
        self.files = files

    def execute(self, context: WorkflowContext) -> None:
        marker = "__GAMEDB_SQL_FILE_COMPLETE__"
        commands = []
        for index, path in enumerate(self.files, 1):
            value = str(path)
            if "'" in value or "\n" in value:
                raise ValueError(f"Unsupported SQL path: {path}")
            commands.append(f"\\ir '{value}'")
            commands.append(f"\\echo {marker}:{index}:{path.name}")

        progress = SqlBatchProgress(self.name, len(self.files))
        progress.update(0, "starting")
        process = subprocess.Popen(
            ["psql", "-X", "-v", "ON_ERROR_STOP=1"],
            cwd=context.project_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write("\n".join(commands) + "\n")
        process.stdin.close()
        for line in process.stdout:
            text = line.rstrip("\n")
            prefix = marker + ":"
            if text.startswith(prefix):
                index_text, filename = text[len(prefix):].split(":", 1)
                progress.update(int(index_text), filename)
            else:
                print(text, flush=True)
        return_code = process.wait()
        if return_code:
            raise subprocess.CalledProcessError(return_code, process.args)


class BuildMediaStep(WorkflowStep):
    """Build selected external media after software scoring is available."""

    def execute(self, context: WorkflowContext) -> None:
        from gamedb.database import create_database_engine
        from gamedb.catalog.media import MediaCatalogBuilder

        MediaCatalogBuilder.from_environment(
            create_database_engine(), context.project_root
        ).execute()


class SqlBatchProgress:
    """Report concrete SQL-file progress for a single transactional batch."""

    WIDTH = 20

    def __init__(self, name: str, total: int):
        self.name = name
        self.total = total
        self.started_at = time.monotonic()

    def update(self, completed: int, label: str) -> None:
        filled = self.WIDTH if not self.total else self.WIDTH * completed // self.total
        bar = "#" * filled + "-" * (self.WIDTH - filled)
        elapsed = int(time.monotonic() - self.started_at)
        print(
            f"  [{bar}] {completed}/{self.total} {label} ({elapsed}s)",
            flush=True,
        )


class StepFactory:
    """Build the executor whose role matches a declarative step type."""

    @staticmethod
    def build(config: StepConfig) -> WorkflowStep:
        if config.type == "run_sql":
            return RunSqlStep(config.name, config.files)
        if config.type == "build_media":
            return BuildMediaStep(config.name)
        raise ValueError(f"Cannot build pipeline step {config.name}: {config.type}")
