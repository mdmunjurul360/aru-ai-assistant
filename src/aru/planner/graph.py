"""Dependency graph validator and topological sorter for ARU AI V4 Planner."""

from __future__ import annotations

from aru.planner.models import PlanStep


class CircularDependencyError(Exception):
    """Raised when steps within a Plan contain circular dependencies."""


class DependencyGraph:
    """Manages DAG validation, cycle detection, and topological ordering for PlanSteps."""

    @classmethod
    def validate_plan(cls, steps: list[PlanStep]) -> list[int]:
        """
        Validate that steps form a valid DAG and return their topological execution order.
        Raises ValueError on missing dependency IDs, or CircularDependencyError on cycles.
        """
        step_ids = {s.id for s in steps}
        adj: dict[int, list[int]] = {s.id: [] for s in steps}
        in_degree: dict[int, int] = {s.id: 0 for s in steps}

        # Build graph: parent -> child
        for step in steps:
            for dep_id in step.depends_on:
                if dep_id not in step_ids:
                    raise ValueError(
                        f"Step {step.id} ('{step.title}') depends on non-existent step {dep_id}."
                    )
                adj[dep_id].append(step.id)
                in_degree[step.id] += 1

        # Kahn's algorithm for topological sorting
        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        order: list[int] = []

        while queue:
            # Deterministic ordering by step ID
            queue.sort()
            curr = queue.pop(0)
            order.append(curr)

            for neighbor in adj[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(steps):
            cycle_nodes = [sid for sid, deg in in_degree.items() if deg > 0]
            raise CircularDependencyError(
                f"Circular dependency detected among plan steps: {cycle_nodes}"
            )

        return order
