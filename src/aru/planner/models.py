"""Domain models for ARU AI V4 Planner."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class StepStatus(str, Enum):
    """Execution status of an individual plan step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Goal(BaseModel):
    """The overarching objective or user intent to be achieved."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    description: str
    user_id: int = 0
    session_id: str = "default"
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PlanStep(BaseModel):
    """A discrete, executable step within a Plan."""

    model_config = ConfigDict(validate_assignment=True)

    id: int
    title: str
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[int] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 2

    @property
    def is_terminal(self) -> bool:
        """Return True if step status is in completed, failed, or skipped."""
        return self.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED)


class Plan(BaseModel):
    """A directed dependency graph of steps aimed at fulfilling a Goal."""

    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    goal: Goal
    steps: list[PlanStep] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_completed(self) -> bool:
        """Check whether all steps are completed or skipped."""
        if not self.steps:
            return True
        return all(s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in self.steps)

    @property
    def has_failures(self) -> bool:
        """Check whether any step has failed."""
        return any(s.status == StepStatus.FAILED for s in self.steps)

    def get_step(self, step_id: int) -> PlanStep | None:
        """Retrieve step by its ID."""
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    def get_runnable_steps(self) -> list[PlanStep]:
        """
        Return pending steps whose upstream dependencies are all completed.
        """
        completed_ids = {s.id for s in self.steps if s.status == StepStatus.COMPLETED}
        runnable: list[PlanStep] = []

        for step in self.steps:
            if step.status != StepStatus.PENDING:
                continue
            # If all dependencies are satisfied
            if set(step.depends_on).issubset(completed_ids):
                runnable.append(step)

        return runnable

    def mark_step_completed(self, step_id: int, result: Any) -> None:
        """Mark a step as completed with its outcome."""
        step = self.get_step(step_id)
        if step:
            step.status = StepStatus.COMPLETED
            step.result = result
            self.updated_at = datetime.now(timezone.utc).isoformat()

    def mark_step_failed(self, step_id: int, error: str) -> None:
        """Mark a step as failed with error details."""
        step = self.get_step(step_id)
        if step:
            step.status = StepStatus.FAILED
            step.error = error
            self.updated_at = datetime.now(timezone.utc).isoformat()
