"""Ok / Err result wrapper.

Used at module boundaries where callers must handle both outcomes explicitly.
A minimal implementation — no third-party dependency, no pattern matching.
"""

from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E")


class Ok(Generic[T]):
    __slots__ = ("_value",)

    def __init__(self, value: T) -> None:
        self._value = value

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False

    def unwrap(self) -> T:
        return self._value

    def unwrap_or(self, default: T) -> T:  # type: ignore[override]
        return self._value


class Err(Generic[E]):
    __slots__ = ("_error",)

    def __init__(self, error: E) -> None:
        self._error = error

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True

    def unwrap(self) -> T:  # type: ignore[override,return-value]
        raise RuntimeError(self._error)  # type: ignore[arg-type]

    def unwrap_or(self, default: T) -> T:  # type: ignore[override]
        return default

    def unwrap_err(self) -> E:
        return self._error