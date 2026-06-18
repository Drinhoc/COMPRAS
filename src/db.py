"""Camada de banco de dados (SQLite local ou Postgres em produção)."""

from __future__ import annotations

import os
from typing import Iterable

from sqlalchemy import Column, Float, Integer, LargeBinary, MetaData, String, Table, create_engine, inspect, text, Date

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
    Column("projeto", String),
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
    Column("created_at", String, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", String, server_default=text("CURRENT_TIMESTAMP")),
)

orcamentos = Table(
    "orcamentos",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("requisicao_id", Integer, nullable=False),
    Column("fornecedor", String),
    Column("valor", Float),
    Column("prazo_entrega", String),
    Column("condicoes_pagamento", String),
    Column("status_orcamento", String),
    Column("observacao", String),
    Column("created_at", String, server_default=text("CURRENT_TIMESTAMP")),
)

anexos = Table(
    "anexos",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("requisicao_id", Integer, nullable=False),
    Column("orcamento_id", Integer),
    Column("tipo", String),
    Column("nome_arquivo", String, nullable=False),
    Column("mime_type", String),
    Column("conteudo", LargeBinary, nullable=False),
    Column("uploaded_at", String, server_default=text("CURRENT_TIMESTAMP")),
    Column("uploaded_by", String),
)

itens = Table(
    "itens",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("requisicao_id", Integer, nullable=False),
    Column("descricao", String, nullable=False),
    Column("quantidade", Float),
    Column("unidade", String),
    Column("valor_unitario", Float),
    Column("observacao", String),
)

aprovacoes = Table(
    "aprovacoes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("requisicao_id", Integer, nullable=False),
    Column("orcamento_id", Integer),
    Column("acao", String, nullable=False),
    Column("comentario", String),
    Column("aprovador", String),
    Column("created_at", String, server_default=text("CURRENT_TIMESTAMP")),
)

projetos = Table(
    "projetos",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String, nullable=False, unique=True),
    Column("descricao", String),
    Column("criado_em", String, server_default=text("CURRENT_TIMESTAMP")),
)

usuarios = Table(
    "usuarios",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String, nullable=False),
    Column("login", String, nullable=False, unique=True),
    Column("senha_hash", String, nullable=False),
    Column("salt", String, nullable=False),
    Column("papel", String, nullable=False),  # ADM | GESTOR | COMPRADOR
    Column("ativo", Integer, server_default=text("1")),
    Column("created_at", String, server_default=text("CURRENT_TIMESTAMP")),
)

eventos = Table(
    "eventos",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("usuario", String),
    Column("papel", String),
    Column("acao", String, nullable=False),
    Column("entidade", String),
    Column("entidade_id", String),
    Column("detalhe", String),
    Column("created_at", String, server_default=text("CURRENT_TIMESTAMP")),
)


def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def get_database_url() -> str:
    return _normalize_database_url(os.getenv("DATABASE_URL", DEFAULT_SQLITE_URL))


def is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite")


def get_engine():
    database_url = get_database_url()
    if database_url.startswith("sqlite"):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        return create_engine(database_url, connect_args={"check_same_thread": False})
    return create_engine(database_url)


ENGINE = get_engine()


def init_db() -> None:
    metadata.create_all(ENGINE)

    inspector = inspect(ENGINE)
    if not inspector.has_table("requisicoes"):
        return

    columns = {col["name"] for col in inspector.get_columns("requisicoes")}
    if "projeto" not in columns:
        with ENGINE.begin() as conn:
            conn.execute(text("ALTER TABLE requisicoes ADD COLUMN projeto VARCHAR"))

    # Migração: colunas de auditoria
    for _col in ("created_at", "updated_at"):
        if _col not in columns:
            with ENGINE.begin() as conn:
                conn.execute(text(f"ALTER TABLE requisicoes ADD COLUMN {_col} VARCHAR"))

    # Migração: coluna orcamento_id em aprovacoes (aprovação por orçamento)
    if inspector.has_table("aprovacoes"):
        apr_cols = {col["name"] for col in inspector.get_columns("aprovacoes")}
        if "orcamento_id" not in apr_cols:
            with ENGINE.begin() as conn:
                conn.execute(text("ALTER TABLE aprovacoes ADD COLUMN orcamento_id INTEGER"))

    # Migração: cria um item a partir dos campos legados para requisições sem itens
    if inspector.has_table("itens"):
        with ENGINE.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO itens (requisicao_id, descricao, quantidade, valor_unitario, observacao) "
                    "SELECT r.id, r.item, r.qtde, r.valor, r.observacao FROM requisicoes r "
                    "WHERE r.item IS NOT NULL AND TRIM(r.item) != '' "
                    "AND NOT EXISTS (SELECT 1 FROM itens i WHERE i.requisicao_id = r.id)"
                )
            )

    # Popula tabela projetos com nomes já existentes em requisicoes (migração única)
    with ENGINE.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT UPPER(TRIM(projeto)) AS nome FROM requisicoes "
                "WHERE projeto IS NOT NULL AND TRIM(projeto) != ''"
            )
        ).fetchall()
        for row in rows:
            conn.execute(
                text(
                    "INSERT INTO projetos (nome) "
                    "SELECT :nome WHERE NOT EXISTS "
                    "(SELECT 1 FROM projetos WHERE UPPER(TRIM(nome)) = UPPER(TRIM(:nome)))"
                ),
                {"nome": row.nome},
            )


def insert_many(rows: Iterable[dict]) -> int:
    columns = ", ".join(COLUMN_ORDER)
    placeholders = ", ".join([":" + col for col in COLUMN_ORDER])
    query = text(f"INSERT INTO requisicoes ({columns}) VALUES ({placeholders})")
    with ENGINE.begin() as conn:
        result = conn.execute(query, list(rows))
        return result.rowcount
