"""Shared V3 operations-database folder layout."""

from __future__ import annotations

from pathlib import Path


PRODUCT_DATABASE_DIR = "1.产品数据库"
ORDER_DATABASE_DIR = "2.订单数据库"
AFTER_SALE_DATABASE_DIR = "3.售后数据库"
PROMOTION_DATABASE_DIR = "4.推广数据库"
OPERATIONS_LOG_DIR = "5.运营操作日志"
PRODUCT_ID_DATABASE_DIR = "6.商品ID库"
INPUT_DIR = "下载未分类"
SYSTEM_DIR = "_系统"

REPORT_ROOT_BY_TYPE = {
    "商品数据": PRODUCT_DATABASE_DIR,
    "订单数据": ORDER_DATABASE_DIR,
    "售后数据": AFTER_SALE_DATABASE_DIR,
    "推广数据": PROMOTION_DATABASE_DIR,
    "推广调整日志": OPERATIONS_LOG_DIR,
}

REQUIRED_DIRECTORIES = (
    PRODUCT_DATABASE_DIR,
    ORDER_DATABASE_DIR,
    AFTER_SALE_DATABASE_DIR,
    PROMOTION_DATABASE_DIR,
    OPERATIONS_LOG_DIR,
    PRODUCT_ID_DATABASE_DIR,
    INPUT_DIR,
    SYSTEM_DIR,
)


def report_root(database_root: Path, report_type: str) -> Path:
    return database_root / REPORT_ROOT_BY_TYPE.get(report_type, report_type)


def product_map_path(database_root: Path) -> Path:
    return database_root / PRODUCT_ID_DATABASE_DIR / "商品ID与店铺映射.csv"


def ensure_layout(database_root: Path) -> list[Path]:
    created: list[Path] = []
    database_root.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_DIRECTORIES:
        target = database_root / name
        if not target.exists():
            target.mkdir(parents=True)
            created.append(target)
    return created
