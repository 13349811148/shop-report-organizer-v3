"""Deterministic V3 product-cost selection and reminder rules."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable


MONEY_QUANTUM = Decimal("0.01")
DEFAULT_DIFFERENCE_TOLERANCE = Decimal("0.01")


def money(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "").replace("￥", "").replace("¥", "")
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed >= 0 else None


def rounded_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ArrivalPrice:
    value: Decimal
    effective_start: dt.date | None = None
    effective_end: dt.date | None = None
    policy_id: str = ""
    tier: str = ""
    tier_confirmed: bool = True
    specificity: int = 0

    def is_effective(self, as_of: dt.date) -> bool:
        if self.effective_start and as_of < self.effective_start:
            return False
        if self.effective_end and as_of > self.effective_end:
            return False
        return True


@dataclass
class CostResolution:
    cost: Decimal | None
    cost_source: str
    reminders: list[str] = field(default_factory=list)
    selected_policy_id: str = ""
    selected_tier: str = ""

    @property
    def status(self) -> str:
        if self.cost_source == "到位价":
            return "正常－取到位价"
        if self.cost_source == "月返价":
            return "正常－取月返价"
        if self.cost_source == "ERP成本价":
            return "兜底－仅有ERP成本价"
        return "待确认－缺少可用成本"


def resolve_cost(
    *,
    as_of: dt.date,
    arrival_prices: Iterable[ArrivalPrice] = (),
    monthly_rebate_price: object = None,
    erp_cost: object = None,
    policy_should_have_arrival: bool = False,
    difference_tolerance: Decimal = DEFAULT_DIFFERENCE_TOLERANCE,
) -> CostResolution:
    """Resolve cost without overwriting source prices.

    An effective, confirmed arrival price wins. If none is usable, use the
    monthly post-rebate unit price. ERP cost is comparison evidence and is
    used only when both preferred sources are absent.
    """

    monthly = money(monthly_rebate_price)
    erp = money(erp_cost)
    reminders: list[str] = []

    active = [item for item in arrival_prices if item.is_effective(as_of)]
    confirmed = [item for item in active if item.tier_confirmed]
    if active and not confirmed:
        reminders.append("待确认－存在多个政策档位但尚未确认适用档位")

    selected: ArrivalPrice | None = None
    if confirmed:
        confirmed.sort(
            key=lambda item: (
                item.specificity,
                item.effective_start or dt.date.min,
            ),
            reverse=True,
        )
        top = confirmed[0]
        conflicts = [
            item
            for item in confirmed[1:]
            if item.specificity == top.specificity
            and (item.effective_start or dt.date.min) == (top.effective_start or dt.date.min)
            and rounded_money(item.value) != rounded_money(top.value)
        ]
        if conflicts:
            reminders.append("待确认－同一日期存在冲突的到位价政策")
        else:
            selected = top

    if monthly is not None and erp is not None:
        difference = abs(rounded_money(monthly) - rounded_money(erp))
        if difference > difference_tolerance:
            reminders.append(
                "待确认－ERP与月返价不一致"
                f"（ERP={rounded_money(erp)}，月返价={rounded_money(monthly)}，差额={difference}）"
            )

    if selected is not None:
        return CostResolution(
            cost=selected.value,
            cost_source="到位价",
            reminders=reminders,
            selected_policy_id=selected.policy_id,
            selected_tier=selected.tier,
        )

    if policy_should_have_arrival:
        reminders.append("提醒－有政策但到位价未填，暂取月返价")

    if monthly is not None:
        return CostResolution(monthly, "月返价", reminders)
    if erp is not None:
        reminders.append("提醒－缺少月返价，暂以ERP成本价兜底")
        return CostResolution(erp, "ERP成本价", reminders)

    reminders.append("待确认－到位价、月返价和ERP成本价均缺失")
    return CostResolution(None, "", reminders)
