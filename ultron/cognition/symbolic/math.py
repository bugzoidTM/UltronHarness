"""Avaliador aritmético restrito por AST; nunca executa código arbitrário."""

from __future__ import annotations

import ast
import operator
from decimal import Decimal
from typing import Final


class UnsafeExpressionError(ValueError):
    """A expressão contém sintaxe fora da whitelist simbólica."""


_BINARY: Final = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: Final = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def evaluate(expression: str) -> int | float:
    """Avalia somente números e operadores aritméticos explícitos.

    A profundidade, o tamanho e o expoente são limitados para manter o caminho
    determinístico e evitar consumo excessivo de recursos.
    """
    if not expression or len(expression) > 200:
        raise UnsafeExpressionError("Expressão ausente ou excede o limite simbólico")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError("Sintaxe matemática inválida") from exc

    def visit(node: ast.AST, depth: int = 0) -> int | float:
        if depth > 20:
            raise UnsafeExpressionError("Profundidade matemática excedida")
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            if isinstance(node.value, float) and not Decimal(str(node.value)).is_finite():
                raise UnsafeExpressionError("Número não finito")
            return node.value
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](visit(node.operand, depth + 1))
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and (abs(right) > 12 or abs(left) > 1_000_000):
                raise UnsafeExpressionError("Expoente fora do limite simbólico")
            try:
                result = _BINARY[type(node.op)](left, right)
            except (ArithmeticError, OverflowError, ZeroDivisionError) as exc:
                raise UnsafeExpressionError("Operação matemática inválida") from exc
            if isinstance(result, float) and not Decimal(str(result)).is_finite():
                raise UnsafeExpressionError("Resultado não finito")
            return result
        raise UnsafeExpressionError(f"Nó não permitido: {type(node).__name__}")

    return visit(tree.body)
