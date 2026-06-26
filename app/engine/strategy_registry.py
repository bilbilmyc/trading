"""StrategyRegistry — round-trip persistence for strategies.

Each strategy declares its own snapshot and restore functions. The registry
dispatches by class name. Forward-compat: restoring an unknown class returns
None (the engine skips it on startup).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List


@dataclass(frozen=True)
class _Registration:
    cls: type
    snapshot: Callable[[Any], Dict[str, Any]]
    restore: Callable[[Dict[str, Any]], Any]


class StrategyRegistry:
    def __init__(self) -> None:
        self._by_name: Dict[str, _Registration] = {}

    def register(
        self,
        cls: type,
        snapshot: Callable[[Any], Dict[str, Any]],
        restore: Callable[[Dict[str, Any]], Any],
    ) -> None:
        """Bind (cls, snapshot_fn, restore_fn) under cls.__name__."""

        self._by_name[cls.__name__] = _Registration(cls=cls, snapshot=snapshot, restore=restore)

    def snapshot(self, strategy: Any) -> Dict[str, Any]:
        """Capture the strategy's persistent state via its declared snapshot fn."""

        reg = self._by_name.get(type(strategy).__name__)
        if reg is None:
            return {}
        return reg.snapshot(strategy)

    def restore(self, item: Dict[str, Any]) -> Any | None:
        """Rebuild a strategy instance from a persisted dict.

        Returns None when the class isn't registered (forward-compat).
        """

        class_name = item.get("class_name")
        if not class_name:
            return None
        reg = self._by_name.get(class_name)
        if reg is None:
            return None
        try:
            return reg.restore(item.get("state", {}))
        except Exception:
            return None

    def registered_classes(self) -> List[str]:
        return sorted(self._by_name.keys())


__all__ = ["StrategyRegistry"]