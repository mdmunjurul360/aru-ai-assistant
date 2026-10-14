"""Plan execution runtime engine for ARU AI V4."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from aru.core.logging import StructuredLogger
from aru.executor.reflection import ReflectionEngine
from aru.executor.state import (
    ExecutionHistory,
    ExecutionState,
    ExecutionStepRecord,
)
from aru.planner.models import Plan, PlanStep, StepStatus
from aru.planner.replanner import Replanner
from aru.tools.executor import ToolExecutor
from aru.tools.models import ExecutionContext, ToolResult


class PlanExecutor:
    """
    State-machine driven execution engine with iteration bounding,
    timeout protection, data piping, reflection, and automated error recovery.
    """

    def __init__(
        self,
        tool_executor: ToolExecutor,
        logger: StructuredLogger | None = None,
        max_iterations: int = 10,
        timeout_seconds: float = 90.0,
        enable_replanning: bool = True,
    ) -> None:
        self._tool_executor = tool_executor
        self._logger = logger or StructuredLogger("aru.executor.engine")
        self._max_iterations = max_iterations
        self._timeout_seconds = timeout_seconds
        self._enable_replanning = enable_replanning

    def _resolve_step_arguments(self, args: dict[str, Any], plan: Plan) -> dict[str, Any]:
        """
        Pipe outputs from upstream dependencies into step arguments.
        Replaces references like '{step_1_output}' or passes upstream results.
        """
        resolved: dict[str, Any] = {}
        completed_outputs = {s.id: s.result for s in plan.steps if s.status == StepStatus.COMPLETED}

        for k, v in args.items():
            if isinstance(v, str):
                # Pattern match {step_X_output}
                for sid, res in completed_outputs.items():
                    tag = f"{{step_{sid}_output}}"
                    if tag in v:
                        v = v.replace(tag, str(res))
            resolved[k] = v
        return resolved

    async def execute_plan(
        self,
        plan: Plan,
        context: ExecutionContext | None = None,
    ) -> ExecutionHistory:
        """
        Execute an entire plan to completion or failure with bounds enforcement.
        """
        history = ExecutionHistory(plan_id=plan.id, state=ExecutionState.RUNNING)
        ctx = context or ExecutionContext(user_id=plan.goal.user_id, is_boss=False)

        start_time = time.perf_counter()
        iteration = 0

        self._logger.info("Starting execution of Plan %s (Goal: %s)", plan.id, plan.goal.description)

        try:
            # Enforce overall plan timeout
            while not plan.is_completed and iteration < self._max_iterations:
                # Check elapsed time
                elapsed = time.perf_counter() - start_time
                if elapsed > self._timeout_seconds:
                    history.state = ExecutionState.FAILED
                    history.error = f"Execution exceeded maximum timeout of {self._timeout_seconds}s."
                    self._logger.error("Plan %s timed out after %.2fs", plan.id, elapsed)
                    return history

                # Identify unblocked runnable steps
                runnable_steps = plan.get_runnable_steps()
                if not runnable_steps:
                    # Deadlock check: steps remain but none are runnable
                    if plan.has_failures or not plan.is_completed:
                        history.state = ExecutionState.FAILED
                        history.error = "Execution blocked: No runnable steps available."
                        self._logger.error("Plan %s deadlocked: No runnable steps.", plan.id)
                        return history
                    break

                for step in runnable_steps:
                    iteration += 1
                    history.iteration_count = iteration

                    if iteration > self._max_iterations:
                        history.state = ExecutionState.FAILED
                        history.error = f"Execution exceeded maximum iteration cap of {self._max_iterations}."
                        self._logger.error("Plan %s exceeded iteration limit.", plan.id)
                        return history

                    step.status = StepStatus.IN_PROGRESS
                    step_start = time.perf_counter()

                    # 1. Pipe arguments
                    resolved_args = self._resolve_step_arguments(step.args, plan)

                    # 2. Execute via ToolExecutor
                    self._logger.info(
                        "[Iteration %d] Executing Step %d: '%s' via tool '%s'",
                        iteration,
                        step.id,
                        step.title,
                        step.tool_name,
                    )
                    res: ToolResult = await self._tool_executor.execute(
                        tool_name=step.tool_name,
                        arguments=resolved_args,
                        context=ctx,
                    )
                    step_duration_ms = (time.perf_counter() - step_start) * 1000

                    # 3. Reflection
                    reflection = ReflectionEngine.evaluate(step, res)

                    if reflection.success:
                        plan.mark_step_completed(step.id, result=res.output)
                        record = ExecutionStepRecord(
                            step_id=step.id,
                            tool_name=step.tool_name,
                            args=resolved_args,
                            output=res.output,
                            state=ExecutionState.COMPLETED,
                            duration_ms=step_duration_ms,
                        )
                        history.add_record(record)
                        self._logger.info("Step %d completed successfully.", step.id)
                    else:
                        # Step failed
                        step.error = res.error
                        record = ExecutionStepRecord(
                            step_id=step.id,
                            tool_name=step.tool_name,
                            args=resolved_args,
                            error=res.error,
                            state=ExecutionState.FAILED,
                            duration_ms=step_duration_ms,
                        )
                        history.add_record(record)
                        self._logger.warning("Step %d failed: %s", step.id, res.error)

                        # Retry logic
                        if Replanner.can_retry_step(step):
                            Replanner.retry_step(plan, step.id)
                            self._logger.info("Step %d queued for retry (attempt %d).", step.id, step.retry_count)
                            continue

                        # Replanning / Fallback
                        if self._enable_replanning:
                            self._logger.info("Attempting dynamic fallback for Step %d...", step.id)
                            try:
                                fallback = Replanner.insert_fallback_step(
                                    plan=plan,
                                    failed_step_id=step.id,
                                    fallback_tool="calculator" if step.tool_name != "calculator" else "memory",
                                    fallback_args={"expression": "0"} if step.tool_name != "calculator" else {"action": "search", "query": "fallback"},
                                    fallback_title=f"Emergency Fallback for Step {step.id}",
                                )
                                self._logger.info("Inserted fallback step %d.", fallback.id)
                                continue
                            except Exception as rep_err:
                                self._logger.error("Replanning failed: %s", rep_err)

                        # Mark failed permanently
                        plan.mark_step_failed(step.id, error=res.error or "Step execution failed.")
                        history.state = ExecutionState.FAILED
                        history.error = f"Step {step.id} failed: {res.error}"
                        return history

            # Final evaluation
            if plan.is_completed:
                history.state = ExecutionState.COMPLETED
                self._logger.info("Plan %s completed successfully in %.2fms.", plan.id, history.total_duration_ms)
            elif iteration >= self._max_iterations:
                history.state = ExecutionState.FAILED
                history.error = f"Execution exceeded maximum iteration cap of {self._max_iterations}."
                self._logger.error("Plan %s terminated due to iteration cap.", plan.id)
            else:
                history.state = ExecutionState.FAILED
                history.error = "Plan execution terminated before completing all steps."

            return history

        except Exception as unhandled_err:
            history.state = ExecutionState.FAILED
            history.error = f"Unhandled execution error: {unhandled_err}"
            self._logger.exception("Plan %s crashed: %s", plan.id, unhandled_err)
            return history
