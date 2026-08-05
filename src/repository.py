"""Read and index Olist CSV files for the domain agents."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path


class OlistRepository:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.orders = self._index_one("olist_orders_dataset.csv", "order_id")
        self.customers = self._index_one("olist_customers_dataset.csv", "customer_id")
        self.products = self._index_one("olist_products_dataset.csv", "product_id")
        self.sellers = self._index_one("olist_sellers_dataset.csv", "seller_id")
        self.translations = self._index_one(
            "product_category_name_translation.csv", "product_category_name"
        )
        self.items_by_order = self._index_many("olist_order_items_dataset.csv", "order_id")
        self.payments_by_order = self._index_many("olist_order_payments_dataset.csv", "order_id")
        self.orders_by_customer = self._index_many_from_rows("customer_id", self.orders.values())

    def _read_csv(self, filename: str) -> list[dict[str, str]]:
        # utf-8-sig also accepts ordinary UTF-8 and removes a possible BOM in CSV headers.
        with (self.data_dir / filename).open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def _index_one(self, filename: str, key: str) -> dict[str, dict[str, str]]:
        return {row[key]: row for row in self._read_csv(filename)}

    def _index_many(self, filename: str, key: str) -> dict[str, list[dict[str, str]]]:
        return self._index_many_from_rows(key, self._read_csv(filename))

    @staticmethod
    def _index_many_from_rows(key: str, rows) -> dict[str, list[dict[str, str]]]:
        indexed: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            indexed[row[key]].append(row)
        return indexed
