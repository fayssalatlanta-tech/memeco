"""
Tests for the batched risk_check inserter.

The previous implementation issued one ``pool.acquire()`` round-trip per
risk_check row — about 12 acquisitions per ingested token. The new
implementation batches into a single transaction with one ``executemany``.
These tests pin that behavior with a fake pool so a regression is caught
without needing a real Postgres instance.
"""

import asyncio
import unittest
from decimal import Decimal
from typing import Any

from app.risk import add_basic_risk_checks


class _FakeConnection:
    def __init__(self) -> None:
        self.executemany_calls: list[tuple[str, list[tuple[Any, ...]]]] = []
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.transaction_count = 0

    def transaction(self) -> "_FakeTransaction":
        self.transaction_count += 1
        return _FakeTransaction()

    async def executemany(self, sql: str, args_iter: list[tuple[Any, ...]]) -> None:
        self.executemany_calls.append((sql, list(args_iter)))

    async def execute(self, sql: str, *args: Any) -> None:
        self.execute_calls.append((sql, args))

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any]:
        self.fetchrow_calls.append((sql, args))
        # Mirror the columns ``insert_risk_check`` selects via RETURNING.
        return {
            "id": 1,
            "token_id": args[0],
            "pair_id": args[1],
            "run_id": args[2],
            "check_category": args[3],
            "check_name": args[4],
            "risk_level": args[5],
            "score": args[6],
            "details": args[7],
            "created_at": None,
        }


class _FakeTransaction:
    async def __aenter__(self) -> "_FakeTransaction":
        return self

    async def __aexit__(self, *_exc_info: Any) -> None:
        return None


class _FakeAcquireContext:
    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConnection:
        return self._conn

    async def __aexit__(self, *_exc_info: Any) -> None:
        return None


class _FakePool:
    def __init__(self) -> None:
        self.conn = _FakeConnection()
        self.acquire_count = 0

    def acquire(self) -> _FakeAcquireContext:
        self.acquire_count += 1
        return _FakeAcquireContext(self.conn)


class AddBasicRiskChecksBatchingTests(unittest.TestCase):
    """``add_basic_risk_checks`` must batch all inserts into one transaction."""

    def test_uses_one_acquire_one_executemany(self) -> None:
        pool = _FakePool()

        rows_inserted = asyncio.run(
            add_basic_risk_checks(
                pool=pool,  # type: ignore[arg-type]
                token_id=1,
                pair_id=2,
                run_id=3,
                token_address="SoTokenAddrAAA",
                pair_address="PairAAA",
                price_usd=Decimal("0.001"),
                liquidity_usd=Decimal("10000"),
                volume_5m_usd=Decimal("2000"),
                volume_1h_usd=Decimal("12000"),
                market_cap_usd=Decimal("100000"),
                fdv_usd=Decimal("200000"),
                pair_created_at="2026-05-24T11:38:00Z",
                txns={"h1": {"buys": 10, "sells": 4}},
                price_change={"h1": 5.0},
            )
        )

        # One pool.acquire() in total, regardless of how many rows.
        self.assertEqual(pool.acquire_count, 1)
        # One transaction, one executemany.
        self.assertEqual(pool.conn.transaction_count, 1)
        self.assertEqual(len(pool.conn.executemany_calls), 1)
        # No legacy single-row inserts leaking through.
        self.assertEqual(pool.conn.execute_calls, [])
        self.assertEqual(pool.conn.fetchrow_calls, [])

        # 10 distinct checks: price + liquidity + volume_5m
        # + 6 data-quality probes (volume_1h, market_cap, fdv,
        # pair_created_at, txns, price_change).
        sql, args_iter = pool.conn.executemany_calls[0]
        self.assertIn("INSERT INTO risk_checks", sql)
        self.assertEqual(rows_inserted, len(args_iter))
        self.assertEqual(rows_inserted, 9)

    def test_low_liquidity_emits_danger_row(self) -> None:
        pool = _FakePool()

        asyncio.run(
            add_basic_risk_checks(
                pool=pool,  # type: ignore[arg-type]
                token_id=1,
                pair_id=2,
                run_id=3,
                token_address="X",
                pair_address="Y",
                price_usd=Decimal("0.001"),
                liquidity_usd=Decimal("100"),  # well below MIN_LIQUIDITY_USD
                volume_5m_usd=Decimal("2000"),
                volume_1h_usd=Decimal("12000"),
                market_cap_usd=Decimal("100000"),
                fdv_usd=Decimal("200000"),
                pair_created_at="2026-05-24T11:38:00Z",
                txns={"h1": {"buys": 1}},
                price_change={"h1": 0.1},
            )
        )

        _, args_iter = pool.conn.executemany_calls[0]
        # Risk level is the 6th positional arg (index 5).
        risk_levels = [row[5] for row in args_iter]
        check_names = [row[4] for row in args_iter]
        self.assertIn("DANGER", risk_levels)
        self.assertIn("low_liquidity", check_names)


if __name__ == "__main__":
    unittest.main()
