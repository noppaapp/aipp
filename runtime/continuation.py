"""Bounded autonomous continuation for the AIPP task lifecycle.

The loop advances only after verification. Authority approval remains an
external gate and is never synthesized by this module.
"""
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class ContinuationHalt(RuntimeError):
    """Raised when continuation cannot safely proceed."""


@dataclass(frozen=True)
class ContinuationResult(Generic[T]):
    result: T
    attempts: int


def continue_verified(
    task: T,
    execute: Callable[[T], T],
    verify: Callable[[T], bool],
    max_attempts: int = 3,
) -> ContinuationResult[T]:
    """Execute and verify a task with a hard retry bound.

    A failed verification may be retried, but the loop always halts after
    ``max_attempts``. No authority transition is performed here.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    current = task
    for attempt in range(1, max_attempts + 1):
        current = execute(current)
        if verify(current):
            return ContinuationResult(current, attempt)

    raise ContinuationHalt(
        f"HALT: verification failed after {max_attempts} attempt(s)"
    )
