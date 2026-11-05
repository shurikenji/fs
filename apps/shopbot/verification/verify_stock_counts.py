"""Check available stock excludes accounts reserved by orders."""
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db.queries import account_stocks
from db.queries import _helpers
from db.queries import products


class StockCountsTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_stock_excludes_reserved_accounts(self):
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.executescript("""
                CREATE TABLE categories (id INTEGER, name TEXT, sort_order INTEGER);
                CREATE TABLE products (id INTEGER, category_id INTEGER, product_type TEXT, stock INTEGER, is_active INTEGER, sort_order INTEGER);
                CREATE TABLE account_stocks (id INTEGER, product_id INTEGER, is_sold INTEGER, sold_order_id INTEGER);
                INSERT INTO categories VALUES (1, 'test', 0);
                INSERT INTO products VALUES (1, 1, 'account_stocked', 0, 1, 0), (2, 1, 'account_stocked', 0, 1, 1);
                INSERT INTO account_stocks VALUES (1, 1, 0, NULL), (2, 1, 0, 11), (3, 1, 1, 12);
            """)
            with patch.object(_helpers, "get_db", AsyncMock(return_value=db)), \
                 patch.object(products, "get_db", AsyncMock(return_value=db)):
                self.assertEqual((await products.get_product_by_id(1))["stock"], 1)
                self.assertEqual((await products.get_product_by_id(2))["stock"], 0)
                self.assertEqual([p["stock"] for p in await products.get_all_products()], [1, 0])
                self.assertEqual([p["stock"] for p in await products.get_active_products_by_category(1)], [1, 0])

    async def test_counts_distinguish_available_reserved_and_sold(self):
        async with aiosqlite.connect(":memory:") as db:
            db.row_factory = aiosqlite.Row
            await db.execute("CREATE TABLE account_stocks (product_id INTEGER, is_sold INTEGER, sold_order_id INTEGER)")
            await db.executemany("INSERT INTO account_stocks VALUES (?, ?, ?)", [
                (1, 0, None), (1, 0, 0), (1, 0, 12), (1, 1, 13), (2, 0, None),
            ])
            with patch.object(account_stocks, "get_db", AsyncMock(return_value=db)):
                self.assertEqual(await account_stocks.count_stock(1), {
                    "total": 4, "sold": 1, "reserved": 1, "available": 2,
                })
                self.assertEqual(await account_stocks.count_stock(99), {
                    "total": 0, "sold": 0, "reserved": 0, "available": 0,
                })

    async def test_delete_preserves_reserved_and_sold_stock(self):
        async with aiosqlite.connect(":memory:") as db:
            await db.execute("CREATE TABLE account_stocks (id INTEGER, is_sold INTEGER, sold_order_id INTEGER)")
            await db.executemany("INSERT INTO account_stocks VALUES (?, ?, ?)", [
                (1, 0, None), (2, 0, 12), (3, 1, 13),
            ])
            with patch.object(_helpers, "get_db", AsyncMock(return_value=db)):
                for account_id in (1, 2, 3):
                    await account_stocks.delete_account(account_id)
            cursor = await db.execute("SELECT id FROM account_stocks ORDER BY id")
            self.assertEqual(await cursor.fetchall(), [(2,), (3,)])


if __name__ == "__main__":
    unittest.main()
