"""Position sizing calculator for contract trading.

Pure functions: given entry/SL/leverage/account, compute recommended
quantity and risk metrics. Used by /api/v1/sizing endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SizingResult:
    quantity: float        # contract quantity
    notional: float        # notional value in quote currency
    margin: float          # initial margin required
    risk_amount: float     # loss if SL hit
    risk_pct: float        # risk as fraction of account
    risk_reward_ratio: float  # TP distance / SL distance


def calculate_position_size(
    account_equity: float,
    entry_price: float,
    stop_loss_price: float,
    risk_pct: float = 0.02,
    leverage: float = 1.0,
    take_profit_price: float | None = None,
    contract_size: float = 1.0,
    min_quantity: float = 0.001,
) -> SizingResult:
    """Compute contract quantity sized to risk `risk_pct` of account.

    Loss at SL = abs(entry - SL) * quantity * contract_size
    Set quantity such that loss == account_equity * risk_pct.
    """
    if account_equity <= 0:
        raise ValueError("account_equity must be positive")
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if stop_loss_price <= 0:
        raise ValueError("stop_loss_price must be positive")
    if abs(entry_price - stop_loss_price) < 1e-12:
        raise ValueError("entry and stop_loss are identical")
    if risk_pct <= 0 or risk_pct >= 1:
        raise ValueError("risk_pct must be in (0, 1)")
    if leverage <= 0:
        raise ValueError("leverage must be positive")

    risk_amount = account_equity * risk_pct
    sl_distance = abs(entry_price - stop_loss_price) / entry_price
    raw_quantity = risk_amount / (sl_distance * entry_price * contract_size)

    quantity = max(min_quantity, (int(raw_quantity / min_quantity)) * min_quantity)
    quantity = round(quantity, 6)
    if quantity < min_quantity:
        quantity = min_quantity

    notional = quantity * entry_price * contract_size
    margin = notional / leverage
    actual_risk = abs(entry_price - stop_loss_price) * quantity * contract_size
    actual_risk_pct = actual_risk / account_equity

    rr = 0.0
    if take_profit_price is not None and take_profit_price > 0:
        tp_distance = abs(take_profit_price - entry_price) / entry_price
        if sl_distance > 0:
            rr = tp_distance / sl_distance

    return SizingResult(
        quantity=quantity,
        notional=round(notional, 4),
        margin=round(margin, 4),
        risk_amount=round(actual_risk, 4),
        risk_pct=round(actual_risk_pct, 6),
        risk_reward_ratio=round(rr, 4),
    )


__all__ = ["SizingResult", "calculate_position_size"]