"""Camada de banco de dados (SQLite local ou Postgres em produção)."""

from __future__ import annotations

import os
from typing import Iterable

from sqlalchemy import Column, Float, Integer, MetaData, String, Table, create_engine, text

from .constants import COLUMN_ORDER

DB_PATH = "/data/app.db"
DEFAULT_SQLITE_URL = f"sqlite:///{DB_PATH}"

metadata = MetaData()

requisicoes = Table(
    "requisicoes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("empresa", String, nullable=False),
    Column("setor", String),
    Column("requisicao", String),
    Column("data_solicitacao", String, nullable=False),
    Column("data_compra", String),
    Column("fornecedor", String),
    Column("qtde", Integer),
    Column("item", String, nullable=False),
    Column("entrega", String),
    Column("situacao", String),
    Column("valor", Float),
    Column("valor_desconto", Float),
    Column("nf", String),
    Column("observacao", String),
)


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def get_engine():
    database_url = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL)
    database_url = _normalize_database_url(database_url)
    if database_url.startswith("sqlite"):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        return create_engine(database_url, connect_args={"check_same_thread": False})
    return create_engine(database_url)


ENGINE = get_engine()


def init_db() -> None:
    metadata.create_all(ENGINE)


def insert_many(rows: Iterable[dict]) -> int:
    columns = ", ".join(COLUMN_ORDER)
    placeholders = ", ".join([":" + col for col in COLUMN_ORDER])
    query = text(f"INSERT INTO requisicoes ({columns}) VALUES ({placeholders})")
    with ENGINE.begin() as conn:
        result = conn.execute(query, list(rows))
        return result.rowcount
