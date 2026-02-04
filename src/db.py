"""Camada de banco de dados SQLite."""

from __future__ import annotations

import os
import sqlite3
from typing import Iterable

from .constants import COLUMN_ORDER

DB_PATH = "/data/app.db"


def ensure_db_dir() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def get_connection() -> sqlite3.Connection:
    ensure_db_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_db_dir()
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS requisicoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa TEXT NOT NULL,
                setor TEXT,
                requisicao TEXT,
                data_solicitacao TEXT NOT NULL,
                data_compra TEXT,
                fornecedor TEXT,
                qtde INTEGER,
                item TEXT NOT NULL,
                entrega TEXT,
                situacao TEXT,
                valor REAL,
                valor_desconto REAL,
                nf TEXT,
                observacao TEXT
            )
            """
        )
        conn.commit()


def insert_many(rows: Iterable[dict]) -> int:
    columns = ", ".join(COLUMN_ORDER)
    placeholders = ", ".join([":" + col for col in COLUMN_ORDER])
    with get_connection() as conn:
        cursor = conn.executemany(
            f"INSERT INTO requisicoes ({columns}) VALUES ({placeholders})",
            rows,
        )
        conn.commit()
        return cursor.rowcount
