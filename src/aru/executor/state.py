"""State machine and execution history models for ARU AI V4 Executor."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ExecutionState(str, Enum):
    """Lifecycle states of the PlanExecutor."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionStepRecord(BaseModel):
    """Immutable audit record of a single step execution attempt."""

    model_config = ConfigDict(frozen=True)

    step_id: int
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    output: Any = None
    error: str | None = None
    state: ExecutionState
    duration_ms: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ExecutionHistory(BaseModel):
    """Aggregate trace of all executed steps, timings, and outcomes."""

    model_config = ConfigDict(validate_assignment=True)

    plan_id: str
    state: ExecutionState = ExecutionState.PENDING
    records: list[ExecutionStepRecord] = Field(default_factory=list)
    total_duration_ms: float = 0.0
    error: str | None = None
    iteration_count: int = 0

    def add_record(self, record: ExecutionStepRecord) -> None:
        """Append a step execution record and accumulate duration."""
        self.records.append(record)
        self.total_duration_ms = round(self.total_duration_ms + record.duration_ms, 2)

    @property
    def final_output(self) -> Any:
        """Extract output from the last successfully completed step."""
        for rec in reversed(self.records):
            if rec.state == ExecutionState.COMPLETED and rec.output is not None:
                return rec.output
        return None
