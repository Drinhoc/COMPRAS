"""CRUD e consultas para requisições."""

from __future__ import annotations

from typing import Any

from .constants import COLUMN_ORDER
from .db import get_connection


def build_filters(filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}

    def add_in(field: str, values: list[str] | None) -> None:
        if values:
            placeholders = ", ".join([f":{field}_{i}" for i in range(len(values))])
            clauses.append(f"{field} IN ({placeholders})")
            for i, val in enumerate(values):
                params[f"{field}_{i}"] = val

    add_in("empresa", filters.get("empresa"))
    add_in("setor", filters.get("setor"))
    add_in("fornecedor", filters.get("fornecedor"))
    add_in("situacao", filters.get("situacao"))

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
            "(item LIKE :texto OR observacao LIKE :texto OR requisicao LIKE :texto OR fornecedor LIKE :texto)"
        )
        params["texto"] = f"%{texto}%"

    where_clause = " WHERE " + " AND ".join(clauses) if clauses else ""
    return where_clause, params


def fetch_requisicoes(filters: dict[str, Any], limit: int, offset: int) -> list[dict[str, Any]]:
    where_clause, params = build_filters(filters)
    query = f"SELECT * FROM requisicoes{where_clause} ORDER BY id DESC LIMIT :limit OFFSET :offset"
    params.update({"limit": limit, "offset": offset})
    with get_connection() as conn:
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def count_requisicoes(filters: dict[str, Any]) -> int:
    where_clause, params = build_filters(filters)
    query = f"SELECT COUNT(*) as total FROM requisicoes{where_clause}"
    with get_connection() as conn:
        cursor = conn.execute(query, params)
        return cursor.fetchone()["total"]


def fetch_distinct(field: str) -> list[str]:
    with get_connection() as conn:
        cursor = conn.execute(
            f"SELECT DISTINCT {field} FROM requisicoes WHERE {field} IS NOT NULL AND {field} != '' ORDER BY {field}"
        )
        return [row[0] for row in cursor.fetchall()]


def get_by_id(requisicao_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM requisicoes WHERE id = ?", (requisicao_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def update_requisicao(requisicao_id: int, data: dict[str, Any]) -> None:
    assignments = ", ".join([f"{col} = :{col}" for col in COLUMN_ORDER])
    data["id"] = requisicao_id
    with get_connection() as conn:
        conn.execute(f"UPDATE requisicoes SET {assignments} WHERE id = :id", data)
        conn.commit()


def create_requisicao(data: dict[str, Any]) -> None:
    columns = ", ".join(COLUMN_ORDER)
    placeholders = ", ".join([":" + col for col in COLUMN_ORDER])
    with get_connection() as conn:
        conn.execute(
            f"INSERT INTO requisicoes ({columns}) VALUES ({placeholders})",
            data,
        )
        conn.commit()
