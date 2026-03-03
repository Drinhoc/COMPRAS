"""CRUD e consultas para requisições."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from .constants import COLUMN_ORDER
from .db import ENGINE


def normalize_filter_value(value: str) -> str:
    return value.strip().upper()


def build_filters(filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}

    def add_in(field_expr: str, values: list[str] | None, param_prefix: str) -> None:
        if values:
            placeholders = ", ".join([f":{param_prefix}_{i}" for i in range(len(values))])
            clauses.append(f"{field_expr} IN ({placeholders})")
            for i, val in enumerate(values):
                params[f"{param_prefix}_{i}"] = normalize_filter_value(val)

    add_in("UPPER(TRIM(empresa))", filters.get("empresa"), "empresa")
    add_in("UPPER(TRIM(setor))", filters.get("setor"), "setor")
    add_in("UPPER(TRIM(fornecedor))", filters.get("fornecedor"), "fornecedor")
    add_in("UPPER(TRIM(situacao))", filters.get("situacao"), "situacao")

    data_sol = filters.get("data_solicitacao")
    if data_sol:
        clauses.append("data_solicitacao BETWEEN :data_sol_ini AND :data_sol_fim")
        params["data_sol_ini"], params["data_sol_fim"] = data_sol

    data_compra = filters.get("data_compra")
    if data_compra:
        clauses.append("data_compra BETWEEN :data_compra_ini AND :data_compra_fim")
        params["data_compra_ini"], params["data_compra_fim"] = data_compra

    texto = filters.get("texto")
    if texto:
        clauses.append(
            "("
            "LOWER(item) LIKE :texto OR LOWER(observacao) LIKE :texto "
            "OR LOWER(requisicao) LIKE :texto OR LOWER(fornecedor) LIKE :texto"
            ")"
        )
        params["texto"] = f"%{texto.lower()}%"

    where_clause = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where_clause, params


def fetch_requisicoes(filters: dict[str, Any], limit: int, offset: int) -> list[dict[str, Any]]:
    where_clause, params = build_filters(filters)
    query = f"SELECT * FROM requisicoes{where_clause} ORDER BY id DESC LIMIT :limit OFFSET :offset"
    params.update({"limit": limit, "offset": offset})
    with ENGINE.connect() as conn:
        cursor = conn.execute(text(query), params)
        return [dict(row._mapping) for row in cursor.fetchall()]


def count_requisicoes(filters: dict[str, Any]) -> int:
    where_clause, params = build_filters(filters)
    query = f"SELECT COUNT(*) as total FROM requisicoes{where_clause}"
    with ENGINE.connect() as conn:
        cursor = conn.execute(text(query), params)
        row = cursor.fetchone()
        return row[0] if row else 0


def fetch_distinct(field: str) -> list[str]:
    query = (
        "SELECT DISTINCT UPPER(TRIM({field})) as value "
        "FROM requisicoes "
        "WHERE {field} IS NOT NULL AND TRIM({field}) != '' "
        "ORDER BY value"
    )
    with ENGINE.connect() as conn:
        cursor = conn.execute(text(query.format(field=field)))
        return [row[0] for row in cursor.fetchall()]


def get_by_id(requisicao_id: int) -> dict[str, Any] | None:
    with ENGINE.connect() as conn:
        cursor = conn.execute(text("SELECT * FROM requisicoes WHERE id = :id"), {"id": requisicao_id})
        row = cursor.fetchone()
        return dict(row._mapping) if row else None


def update_requisicao(requisicao_id: int, data: dict[str, Any]) -> None:
    assignments = ", ".join([f"{col} = :{col}" for col in COLUMN_ORDER])
    data["id"] = requisicao_id
    with ENGINE.begin() as conn:
        conn.execute(text(f"UPDATE requisicoes SET {assignments} WHERE id = :id"), data)


def create_requisicao(data: dict[str, Any]) -> None:
    columns = ", ".join(COLUMN_ORDER)
    placeholders = ", ".join([":" + col for col in COLUMN_ORDER])
    with ENGINE.begin() as conn:
        conn.execute(
            text(f"INSERT INTO requisicoes ({columns}) VALUES ({placeholders})"),
            data,
        )


def delete_requisicao(requisicao_id: int) -> None:
    with ENGINE.begin() as conn:
        conn.execute(text("DELETE FROM requisicoes WHERE id = :id"), {"id": requisicao_id})


# --- Orçamentos ---
def list_orcamentos(requisicao_id: int) -> list[dict[str, Any]]:
    query = "SELECT * FROM orcamentos WHERE requisicao_id = :rid ORDER BY id DESC"
    with ENGINE.connect() as conn:
        cursor = conn.execute(text(query), {"rid": requisicao_id})
        return [dict(r._mapping) for r in cursor.fetchall()]


def create_orcamento(data: dict[str, Any]) -> None:
    query = text(
        """
        INSERT INTO orcamentos (
            requisicao_id, fornecedor, valor, prazo_entrega,
            condicoes_pagamento, status_orcamento, observacao
        ) VALUES (
            :requisicao_id, :fornecedor, :valor, :prazo_entrega,
            :condicoes_pagamento, :status_orcamento, :observacao
        )
        """
    )
    with ENGINE.begin() as conn:
        conn.execute(query, data)


def delete_orcamento(orcamento_id: int) -> None:
    with ENGINE.begin() as conn:
        conn.execute(text("DELETE FROM orcamentos WHERE id = :id"), {"id": orcamento_id})


# --- Anexos (BLOB) ---
def list_anexos(requisicao_id: int) -> list[dict[str, Any]]:
    query = """
        SELECT id, requisicao_id, orcamento_id, tipo, nome_arquivo, mime_type, uploaded_at, uploaded_by
        FROM anexos WHERE requisicao_id = :rid ORDER BY id DESC
    """
    with ENGINE.connect() as conn:
        cursor = conn.execute(text(query), {"rid": requisicao_id})
        return [dict(r._mapping) for r in cursor.fetchall()]


def create_anexo(data: dict[str, Any]) -> None:
    query = text(
        """
        INSERT INTO anexos (
            requisicao_id, orcamento_id, tipo, nome_arquivo, mime_type, conteudo, uploaded_by
        ) VALUES (
            :requisicao_id, :orcamento_id, :tipo, :nome_arquivo, :mime_type, :conteudo, :uploaded_by
        )
        """
    )
    with ENGINE.begin() as conn:
        conn.execute(query, data)


def get_anexo_conteudo(anexo_id: int) -> dict[str, Any] | None:
    query = "SELECT id, nome_arquivo, mime_type, conteudo FROM anexos WHERE id = :id"
    with ENGINE.connect() as conn:
        row = conn.execute(text(query), {"id": anexo_id}).fetchone()
        return dict(row._mapping) if row else None


def delete_anexo(anexo_id: int) -> None:
    with ENGINE.begin() as conn:
        conn.execute(text("DELETE FROM anexos WHERE id = :id"), {"id": anexo_id})


# --- Aprovações ---
def list_aprovacoes(requisicao_id: int) -> list[dict[str, Any]]:
    query = "SELECT * FROM aprovacoes WHERE requisicao_id = :rid ORDER BY id DESC"
    with ENGINE.connect() as conn:
        cursor = conn.execute(text(query), {"rid": requisicao_id})
        return [dict(r._mapping) for r in cursor.fetchall()]


def create_aprovacao(data: dict[str, Any]) -> None:
    query = text(
        """
        INSERT INTO aprovacoes (requisicao_id, acao, comentario, aprovador)
        VALUES (:requisicao_id, :acao, :comentario, :aprovador)
        """
    )
    with ENGINE.begin() as conn:
        conn.execute(query, data)
