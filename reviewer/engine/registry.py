"""Check registry: ``@register_check`` decorator and the ``CHECKS`` list.

Importing ``reviewer.checks`` triggers decorator registration. The runner
reads ``CHECKS`` once per review. Never mutate ``CHECKS`` at runtime — to
disable a check, filter in the runner.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, TypeVar

if TYPE_CHECKING:  # pragma: no cover - only for type hints
    from .visitor import Check

CHECKS: list[type["Check"]] = []

C = TypeVar("C", bound=type)


def register_check(
    *,
    rule_id: str,
    category: str,
    severity: str,
    description: str,
) -> Callable[[C], C]:
    """Decorator: store metadata on a Check subclass and append to CHECKS."""

    def decorator(cls: C) -> C:
        cls.RULE_ID = rule_id            # type: ignore[attr-defined]
        cls.CATEGORY = category          # type: ignore[attr-defined]
        cls.DEFAULT_SEVERITY = severity  # type: ignore[attr-defined]
        cls.DESCRIPTION = description    # type: ignore[attr-defined]
        CHECKS.append(cls)
        return cls

    return decorator
