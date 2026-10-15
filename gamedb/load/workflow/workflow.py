"""Ordered execution of configured GameDB loader layers."""

from __future__ import annotations

from gamedb.config import ProjectEnvironment

from .config import WorkflowConfig
from .steps import StepFactory, WorkflowContext


class RebuildWorkflow:
    """Plan or execute layers exactly as declared in the pipeline YAML."""

    def __init__(self, config: WorkflowConfig):
        self.config = config

    def describe(self) -> str:
        lines = [f"Pipeline: {self.config.name}"]
        for layer in self.config.layers:
            lines.append(f"\n{layer.name}: {layer.description}")
            for step in layer.steps:
                lines.append(f"  - {step.name} ({step.type})")
                lines.extend(f"      {path.name}" for path in step.files)
                if step.load_file is not None:
                    lines.append(f"      {step.load_file.name}")
        return "\n".join(lines)

    def execute(self) -> None:
        ProjectEnvironment(self.config.root / ".env").load()
        context = WorkflowContext(self.config.root)
        total = sum(len(layer.steps) for layer in self.config.layers)
        position = 0
        for layer in self.config.layers:
            print(f"Layer {layer.name}: {layer.description}", flush=True)
            for step_config in layer.steps:
                position += 1
                step = StepFactory.build(step_config)
                print(f"[{position}/{total}] {step.name} started", flush=True)
                step.execute(context)
                print(f"[{position}/{total}] {step.name} finished", flush=True)
