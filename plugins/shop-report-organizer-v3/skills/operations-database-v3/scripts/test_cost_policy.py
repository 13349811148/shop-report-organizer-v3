from __future__ import annotations

import datetime as dt
import unittest
from decimal import Decimal

from cost_policy import ArrivalPrice, resolve_cost


class CostPolicyTests(unittest.TestCase):
    def test_effective_arrival_price_wins(self) -> None:
        result = resolve_cost(
            as_of=dt.date(2026, 9, 1),
            arrival_prices=[
                ArrivalPrice(
                    Decimal("18.88"),
                    effective_start=dt.date(2026, 8, 1),
                    effective_end=dt.date(2026, 11, 30),
                    policy_id="third-cycle",
                )
            ],
            monthly_rebate_price="20.79",
            erp_cost="20.79",
        )
        self.assertEqual(result.cost, Decimal("18.88"))
        self.assertEqual(result.cost_source, "到位价")

    def test_missing_arrival_uses_monthly_and_reminds(self) -> None:
        result = resolve_cost(
            as_of=dt.date(2026, 9, 1),
            monthly_rebate_price="20.79",
            erp_cost="20.79",
            policy_should_have_arrival=True,
        )
        self.assertEqual(result.cost, Decimal("20.79"))
        self.assertIn("提醒－有政策但到位价未填，暂取月返价", result.reminders)

    def test_erp_difference_does_not_override_monthly(self) -> None:
        result = resolve_cost(
            as_of=dt.date(2026, 9, 1),
            monthly_rebate_price="20.79",
            erp_cost="21.10",
        )
        self.assertEqual(result.cost, Decimal("20.79"))
        self.assertTrue(any("ERP与月返价不一致" in item for item in result.reminders))

    def test_expired_arrival_is_not_used(self) -> None:
        result = resolve_cost(
            as_of=dt.date(2026, 12, 1),
            arrival_prices=[
                ArrivalPrice(
                    Decimal("18.88"),
                    effective_end=dt.date(2026, 11, 30),
                )
            ],
            monthly_rebate_price="20.79",
        )
        self.assertEqual(result.cost_source, "月返价")

    def test_unconfirmed_tier_uses_monthly(self) -> None:
        result = resolve_cost(
            as_of=dt.date(2026, 9, 1),
            arrival_prices=[
                ArrivalPrice(Decimal("18.88"), tier="Y4", tier_confirmed=False)
            ],
            monthly_rebate_price="20.79",
        )
        self.assertEqual(result.cost_source, "月返价")
        self.assertTrue(any("政策档位" in item for item in result.reminders))


if __name__ == "__main__":
    unittest.main()
