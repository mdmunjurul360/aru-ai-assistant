"""Dynamic replanning and failure recovery for ARU AI V4 Planner."""

from __future__ import annotations

from typing import Any
from aru.planner.graph import DependencyGraph
from aru.planner.models import Plan, PlanStep, StepStatus


class Replanner:
    """
    Evaluates execution failures in an active Plan and dynamically repairs
    the execution graph by retrying, adapting arguments, or inserting fallback steps.
    """

    @classmethod
    def can_retry_step(cls, step: PlanStep) -> bool:
        """Check whether step is eligible for retry."""
        return step.retry_count < step.max_retries

    @classmethod
    def retry_step(cls, plan: Plan, step_id: int) -> PlanStep | None:
        """Reset failed step to pending status with incremented retry count."""
        step = plan.get_step(step_id)
        if step and cls.can_retry_step(step):
            step.status = StepStatus.PENDING
            step.error = None
            step.retry_count += 1
            return step
        return None

    @classmethod
    def insert_fallback_step(
        cls,
        plan: Plan,
        failed_step_id: int,
        fallback_tool: str,
        fallback_args: dict[str, Any],
        fallback_title: str | None = None,
    ) -> PlanStep:
        """
        Insert an alternative fallback step and re-route downstream dependencies.
        """
        failed_step = plan.get_step(failed_step_id)
        if not failed_step:
            raise ValueError(f"Step {failed_step_id} not found in plan.")

        # Create new step ID higher than existing max
        max_id = max(s.id for s in plan.steps) if plan.steps else 0
        new_step_id = max_id + 1

        fallback_step = PlanStep(
            id=new_step_id,
            title=fallback_title or f"Fallback for Step {failed_step_id}",
            tool_name=fallback_tool,
            args=fallback_args,
            depends_on=list(failed_step.depends_on),
            status=StepStatus.PENDING,
        )

        # Re-route any steps that depended on failed_step_id to depend on new_step_id
        for step in plan.steps:
            if failed_step_id in step.depends_on:
                step.depends_on.remove(failed_step_id)
                step.depends_on.append(new_step_id)

        # Mark failed step as SKIPPED so it does not block the plan
        failed_step.status = StepStatus.SKIPPED

        plan.steps.append(fallback_step)
        DependencyGraph.validate_plan(plan.steps)
        return fallback_step
