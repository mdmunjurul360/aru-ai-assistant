"""Safe mathematical calculator tool for ARU AI V4."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any
from aru.tools.base import BaseTool
from aru.tools.models import ToolPermission, ToolResult


class SafeMathEvaluator(ast.NodeVisitor):
    """Safely evaluates arithmetic expressions using AST inspection without eval()."""

    OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }

    ALLOWED_FUNCTIONS = {
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "log10": math.log10,
        "exp": math.exp,
        "abs": abs,
        "round": round,
        "floor": math.floor,
        "ceil": math.ceil,
    }

    ALLOWED_CONSTANTS = {
        "pi": math.pi,
        "e": math.e,
    }

    def evaluate(self, expr_str: str) -> float | int:
        """Parse and safely evaluate math string."""
        tree = ast.parse(expr_str, mode="eval")
        return self.visit(tree.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant literal: {node.value!r}")

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in self.ALLOWED_CONSTANTS:
            return self.ALLOWED_CONSTANTS[node.id]
        raise ValueError(f"Unsupported variable name: '{node.id}'")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left = self.visit(node.left)
        right = self.visit(node.right)
        op_type = type(node.op)
        if op_type in self.OPERATORS:
            return self.OPERATORS[op_type](left, right)
        raise ValueError(f"Unsupported binary operator: {op_type.__name__}")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        op_type = type(node.op)
        if op_type in self.OPERATORS:
            return self.OPERATORS[op_type](operand)
        raise ValueError(f"Unsupported unary operator: {op_type.__name__}")

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise ValueError("Only direct function calls are supported.")
        func_name = node.func.id
        if func_name not in self.ALLOWED_FUNCTIONS:
            raise ValueError(f"Function '{func_name}' is not in math allowlist.")
        args = [self.visit(arg) for arg in node.args]
        return self.ALLOWED_FUNCTIONS[func_name](*args)

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"Unsupported expression syntax: {type(node).__name__}")


class CalculatorTool(BaseTool):
    """Tool for evaluating exact mathematical and arithmetic computations."""

    name = "calculator"
    description = "Compute mathematical calculations safely (e.g., '(25 * 4) + sqrt(144)')."
    required_permission = ToolPermission.READ
    timeout = 5.0

    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Mathematical expression to evaluate",
            },
        },
        "required": ["expression"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        expr = str(kwargs.get("expression", "")).strip()
        if not expr:
            return ToolResult(success=False, error="Parameter 'expression' is required.")

        try:
            evaluator = SafeMathEvaluator()
            result = evaluator.evaluate(expr)
            return ToolResult(
                success=True,
                output=result,
                metadata={"expression": expr},
            )
        except Exception as err:
            return ToolResult(
                success=False,
                error=f"Math evaluation error: {err}",
                metadata={"expression": expr},
            )
