"""
持仓同步模块

定时从交易所拉取账户余额和持仓信息，同步到本地 PositionManager，
并在覆盖本地状态之前记录可审计的账户/仓位差异。
"""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from app.engine.position_manager import PositionManager
from app.exchanges.base import ExchangeBase
from app.exchanges.contract_base import ContractExchangeBase
from app.models.position import Position


@dataclass
class AccountReconciliationOutcome:
    """One venue reconciliation pass, safe to persist as JSON."""

    exchange: str
    balances: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    balance_sync_ok: bool = False
    position_sync_ok: bool | None = None
    errors: list[str] = field(default_factory=list)
    updated: int = 0
    completed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            "exchange": self.exchange,
            "balances": self.balances,
            "positions": self.positions,
            "issues": self.issues,
            "balance_sync_ok": self.balance_sync_ok,
            "position_sync_ok": self.position_sync_ok,
            "errors": self.errors,
            "updated": self.updated,
            "completed_at": self.completed_at,
        }


class PositionSync:
    """Periodically reconcile exchange account state into ``PositionManager``.

    Balance deltas are retained as warnings.  Contract position quantity and
    direction deltas are *critical* because placing a new order with an
    inaccurate local position can increase real exposure unexpectedly.
    """

    _ABS_TOLERANCE = 1e-9
    _REL_TOLERANCE = 1e-6

    def __init__(
        self,
        position_manager: PositionManager,
        interval_seconds: int = 15,
    ):
        self.position_manager = position_manager
        self.interval_seconds = interval_seconds
        self._callbacks: list = []
        self._reconciliation_callbacks: list = []
        self._last_outcomes: dict[str, AccountReconciliationOutcome] = {}

    def on_sync(self, callback) -> None:
        """Register the historical ``callback(exchange, changed)`` hook."""

        self._callbacks.append(callback)

    def on_reconciliation(self, callback) -> None:
        """Register ``callback(outcome)`` for each completed sync pass."""

        self._reconciliation_callbacks.append(callback)

    def last_outcome(self, exchange: str) -> AccountReconciliationOutcome | None:
        return self._last_outcomes.get(exchange.lower())

    @classmethod
    def _different(cls, left: float, right: float) -> bool:
        return not math.isclose(
            left,
            right,
            rel_tol=cls._REL_TOLERANCE,
            abs_tol=cls._ABS_TOLERANCE,
        )

    @staticmethod
    def _issue(
        *,
        kind: str,
        resource: str,
        severity: str,
        local: dict[str, Any] | None,
        exchange: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "issue_key": f"{kind}:{resource}",
            "kind": kind,
            "resource": resource,
            "severity": severity,
            "local": local,
            "exchange": exchange,
        }

    @staticmethod
    def _position_from_raw(pos_raw: dict[str, Any], fallback_symbol: str | None) -> dict[str, Any]:
        return {
            "symbol": str(pos_raw.get("symbol") or fallback_symbol or ""),
            "quantity": float(
                pos_raw.get("quantity") or pos_raw.get("pos") or pos_raw.get("positionAmt") or 0
            ),
            "avg_entry_price": float(
                pos_raw.get("avg_price") or pos_raw.get("avgPx") or pos_raw.get("entryPrice") or 0
            ),
            "current_price": float(
                pos_raw.get("current_price")
                or pos_raw.get("markPx")
                or pos_raw.get("markPrice")
                or 0
            ),
        }

    async def sync(
        self,
        exchange: ExchangeBase,
        exchange_name: str,
        symbol: str | None = None,
    ) -> int:
        """Sync a venue and publish an :class:`AccountReconciliationOutcome`."""

        exchange_key = exchange_name.lower()
        outcome = AccountReconciliationOutcome(exchange=exchange_key)

        # 1) Balances.  Balance changes can be deposits/transfers, therefore
        # they are intentionally warnings rather than a new-order hard block.
        try:
            balances = await exchange.get_account_balance()
            for currency, total in balances.items():
                available = total
                if isinstance(total, dict):
                    available_val = float(total.get("available", total.get("free", 0)))
                    total_val = float(total.get("total", total.get("balance", 0)))
                else:
                    total_val = float(total)
                    available_val = float(available)
                actual = {
                    "currency": str(currency),
                    "total": total_val,
                    "available": available_val,
                }
                outcome.balances.append(actual)
                local = await self.position_manager.get_balance(exchange_name, str(currency))
                if local is not None and (
                    self._different(local.total, total_val)
                    or self._different(local.available, available_val)
                ):
                    outcome.issues.append(
                        self._issue(
                            kind="balance_mismatch",
                            resource=str(currency),
                            severity="warning",
                            local={"total": local.total, "available": local.available},
                            exchange=actual,
                        )
                    )
                await self.position_manager.update_balance(
                    exchange_name, str(currency), total_val, available_val
                )
                outcome.updated += 1
            outcome.balance_sync_ok = True
        except Exception as exc:
            message = f"balance sync failed: {exc}"
            outcome.errors.append(message)
            logger.warning(f"PositionSync [{exchange_name}] {message}")

        # 2) Contract positions.  Query all positions when possible so a
        # manual/external position cannot remain invisible to the local model.
        if isinstance(exchange, ContractExchangeBase):
            try:
                positions = await exchange.get_positions(symbol)
                actual_by_symbol: dict[str, dict[str, Any]] = {}
                local_positions = await self.position_manager.get_all_positions()
                local_for_exchange = {
                    key.split(":", 1)[1]: value
                    for key, value in local_positions.items()
                    if key.lower().startswith(f"{exchange_key}:")
                }
                for pos_raw in positions:
                    actual = self._position_from_raw(pos_raw, symbol)
                    pos_symbol = actual["symbol"]
                    if not pos_symbol:
                        continue
                    if abs(actual["quantity"]) <= self._ABS_TOLERANCE:
                        continue
                    actual_by_symbol[pos_symbol] = actual
                    outcome.positions.append(actual)
                    local = local_for_exchange.get(pos_symbol)
                    if local is None:
                        outcome.issues.append(
                            self._issue(
                                kind="unexpected_position",
                                resource=pos_symbol,
                                severity="critical",
                                local=None,
                                exchange=actual,
                            )
                        )
                    else:
                        local_payload = {
                            "quantity": local.quantity,
                            "avg_entry_price": local.avg_entry_price,
                            "current_price": local.current_price,
                        }
                        if self._different(local.quantity, actual["quantity"]):
                            outcome.issues.append(
                                self._issue(
                                    kind="position_quantity_mismatch",
                                    resource=pos_symbol,
                                    severity="critical",
                                    local=local_payload,
                                    exchange=actual,
                                )
                            )
                        elif self._different(local.avg_entry_price, actual["avg_entry_price"]):
                            outcome.issues.append(
                                self._issue(
                                    kind="position_price_mismatch",
                                    resource=pos_symbol,
                                    severity="warning",
                                    local=local_payload,
                                    exchange=actual,
                                )
                            )
                    await self._upsert_position(
                        exchange_name,
                        pos_symbol,
                        Position(
                            symbol=pos_symbol,
                            exchange=exchange_name,
                            quantity=actual["quantity"],
                            avg_entry_price=actual["avg_entry_price"],
                            current_price=actual["current_price"],
                        ),
                    )
                    outcome.updated += 1

                # A local non-flat contract position that is absent from the
                # exchange's full response is equally dangerous.
                for pos_symbol, local in local_for_exchange.items():
                    if pos_symbol in actual_by_symbol or abs(local.quantity) <= self._ABS_TOLERANCE:
                        continue
                    outcome.issues.append(
                        self._issue(
                            kind="missing_position",
                            resource=pos_symbol,
                            severity="critical",
                            local={
                                "quantity": local.quantity,
                                "avg_entry_price": local.avg_entry_price,
                                "current_price": local.current_price,
                            },
                            exchange=None,
                        )
                    )
                    await self._upsert_position(
                        exchange_name,
                        pos_symbol,
                        Position(symbol=pos_symbol, exchange=exchange_name, quantity=0),
                    )
                    outcome.updated += 1
                outcome.position_sync_ok = True
            except Exception as exc:
                message = f"contract positions sync failed: {exc}"
                outcome.errors.append(message)
                outcome.position_sync_ok = False
                logger.warning(f"PositionSync [{exchange_name}] {message}")

        self.position_manager.sync_positions_gauge()
        self._last_outcomes[exchange_key] = outcome

        if outcome.updated > 0:
            for cb in self._callbacks:
                try:
                    result = cb(exchange_name, True)
                    if inspect.isawaitable(result):
                        await result
                except Exception as exc:
                    logger.warning(f"PositionSync callback error: {exc}")

        for cb in self._reconciliation_callbacks:
            try:
                result = cb(outcome)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                logger.warning(f"PositionSync reconciliation callback error: {exc}")

        return outcome.updated

    async def _upsert_position(self, exchange_name: str, symbol: str, position: Position) -> None:
        """Directly replace a position with the exchange's authoritative view."""

        key = f"{exchange_name}:{symbol}"
        async with self.position_manager._lock:
            self.position_manager._positions[key] = position
