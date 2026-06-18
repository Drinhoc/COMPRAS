"""CRUD e consultas para requisições."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")

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
    add_in("UPPER(TRIM(projeto))", filters.get("projeto"), "projeto")
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


def fetch_counts(requisicao_ids: list[int]) -> dict[int, dict[str, int]]:
    """Retorna {req_id: {'orcamentos': n, 'anexos': n}} para os IDs informados."""
    result: dict[int, dict[str, int]] = {
        int(rid): {"orcamentos": 0, "anexos": 0} for rid in requisicao_ids
    }
    if not requisicao_ids:
        return result
    placeholders = ", ".join(f":id{i}" for i in range(len(requisicao_ids)))
    params = {f"id{i}": int(rid) for i, rid in enumerate(requisicao_ids)}
    with ENGINE.connect() as conn:
        for tabela, chave in (("orcamentos", "orcamentos"), ("anexos", "anexos")):
            cursor = conn.execute(
                text(
                    f"SELECT requisicao_id, COUNT(*) AS n FROM {tabela} "
                    f"WHERE requisicao_id IN ({placeholders}) GROUP BY requisicao_id"
                ),
                params,
            )
            for row in cursor.fetchall():
                rid = int(row._mapping["requisicao_id"])
                if rid in result:
                    result[rid][chave] = int(row._mapping["n"])
    return result


def get_by_id(requisicao_id: int) -> dict[str, Any] | None:
    with ENGINE.connect() as conn:
        cursor = conn.execute(text("SELECT * FROM requisicoes WHERE id = :id"), {"id": requisicao_id})
        row = cursor.fetchone()
        return dict(row._mapping) if row else None


def update_requisicao(requisicao_id: int, data: dict[str, Any]) -> None:
    # Atualização parcial: só mexe nas colunas presentes em `data`.
    cols = [c for c in COLUMN_ORDER if c in data]
    assignments = ", ".join([f"{col} = :{col}" for col in cols] + ["updated_at = :updated_at"])
    params = {c: data[c] for c in cols}
    params["updated_at"] = _now()
    params["id"] = requisicao_id
    with ENGINE.begin() as conn:
        if "projeto" in data:
            _ensure_projeto_exists(conn, data.get("projeto") or "")
        conn.execute(text(f"UPDATE requisicoes SET {assignments} WHERE id = :id"), params)


def set_valor_requisicao(requisicao_id: int, valor: float) -> None:
    with ENGINE.begin() as conn:
        conn.execute(
            text("UPDATE requisicoes SET valor = :v, updated_at = :u WHERE id = :id"),
            {"v": valor, "u": _now(), "id": requisicao_id},
        )


def _ensure_projeto_exists(conn: Any, nome: str) -> None:
    """Garante que o projeto existe na tabela projetos (upsert pelo nome)."""
    if not nome or not nome.strip():
        return
    conn.execute(
        text(
            "INSERT INTO projetos (nome) "
            "SELECT :nome WHERE NOT EXISTS "
            "(SELECT 1 FROM projetos WHERE UPPER(TRIM(nome)) = UPPER(TRIM(:nome)))"
        ),
        {"nome": nome.strip().upper()},
    )


def create_requisicao(data: dict[str, Any]) -> None:
    all_cols = COLUMN_ORDER + ["created_at", "updated_at"]
    columns = ", ".join(all_cols)
    placeholders = ", ".join([":" + col for col in all_cols])
    params = {c: data.get(c) for c in COLUMN_ORDER}
    params["created_at"] = params["updated_at"] = _now()
    with ENGINE.begin() as conn:
        _ensure_projeto_exists(conn, data.get("projeto") or "")
        conn.execute(
            text(f"INSERT INTO requisicoes ({columns}) VALUES ({placeholders})"),
            params,
        )


def delete_requisicao(requisicao_id: int) -> None:
    with ENGINE.begin() as conn:
        for tabela in ("aprovacoes", "anexos", "orcamentos", "itens"):
            conn.execute(text(f"DELETE FROM {tabela} WHERE requisicao_id = :id"), {"id": requisicao_id})
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


def update_orcamento(orcamento_id: int, data: dict[str, Any]) -> None:
    if not data:
        return
    set_clause = ", ".join(f"{k} = :{k}" for k in data)
    params = dict(data)
    params["id"] = orcamento_id
    with ENGINE.begin() as conn:
        conn.execute(text(f"UPDATE orcamentos SET {set_clause} WHERE id = :id"), params)


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
    data = {
        "requisicao_id": data["requisicao_id"],
        "orcamento_id": data.get("orcamento_id"),
        "acao": data["acao"],
        "comentario": data.get("comentario"),
        "aprovador": data.get("aprovador"),
    }
    query = text(
        """
        INSERT INTO aprovacoes (requisicao_id, orcamento_id, acao, comentario, aprovador)
        VALUES (:requisicao_id, :orcamento_id, :acao, :comentario, :aprovador)
        """
    )
    with ENGINE.begin() as conn:
        conn.execute(query, data)


# --- Itens estruturados ---
def list_itens(requisicao_id: int) -> list[dict[str, Any]]:
    query = "SELECT * FROM itens WHERE requisicao_id = :rid ORDER BY id"
    with ENGINE.connect() as conn:
        cursor = conn.execute(text(query), {"rid": requisicao_id})
        return [dict(r._mapping) for r in cursor.fetchall()]


def replace_itens(requisicao_id: int, rows: list[dict[str, Any]]) -> None:
    """Substitui todos os itens da requisição pelos informados (vindo do data_editor)."""
    insert = text(
        """
        INSERT INTO itens (requisicao_id, descricao, quantidade, unidade, valor_unitario, observacao)
        VALUES (:requisicao_id, :descricao, :quantidade, :unidade, :valor_unitario, :observacao)
        """
    )
    with ENGINE.begin() as conn:
        conn.execute(text("DELETE FROM itens WHERE requisicao_id = :rid"), {"rid": requisicao_id})
        for row in rows:
            descricao = (row.get("descricao") or "").strip()
            if not descricao:
                continue
            conn.execute(
                insert,
                {
                    "requisicao_id": requisicao_id,
                    "descricao": descricao,
                    "quantidade": row.get("quantidade"),
                    "unidade": (row.get("unidade") or "").strip() or None,
                    "valor_unitario": row.get("valor_unitario"),
                    "observacao": (row.get("observacao") or "").strip() or None,
                },
            )


def fetch_itens_resumo(requisicao_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Retorna {req_id: {'primeiro': descricao, 'total': n}} para a lista."""
    result: dict[int, dict[str, Any]] = {}
    if not requisicao_ids:
        return result
    placeholders = ", ".join(f":id{i}" for i in range(len(requisicao_ids)))
    params = {f"id{i}": int(rid) for i, rid in enumerate(requisicao_ids)}
    with ENGINE.connect() as conn:
        cursor = conn.execute(
            text(
                f"SELECT requisicao_id, descricao, id FROM itens "
                f"WHERE requisicao_id IN ({placeholders}) ORDER BY requisicao_id, id"
            ),
            params,
        )
        for row in cursor.fetchall():
            rid = int(row._mapping["requisicao_id"])
            entry = result.setdefault(rid, {"primeiro": row._mapping["descricao"], "total": 0})
            entry["total"] += 1
    return result


def delete_all_data() -> None:
    """Remove todos os dados do sistema (requisições e históricos relacionados)."""
    with ENGINE.begin() as conn:
        if ENGINE.dialect.name == "postgresql":
            conn.execute(text("TRUNCATE TABLE aprovacoes, anexos, orcamentos, itens, requisicoes RESTART IDENTITY CASCADE"))
            return

        conn.execute(text("DELETE FROM aprovacoes"))
        conn.execute(text("DELETE FROM anexos"))
        conn.execute(text("DELETE FROM orcamentos"))
        conn.execute(text("DELETE FROM itens"))
        conn.execute(text("DELETE FROM requisicoes"))

        if ENGINE.dialect.name == "sqlite":
            seq_exists = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'")
            ).fetchone()
            if seq_exists:
                conn.execute(
                    text(
                        "DELETE FROM sqlite_sequence "
                        "WHERE name IN ('requisicoes', 'orcamentos', 'anexos', 'aprovacoes', 'itens')"
                    )
                )


def list_projetos() -> list[str]:
    """Retorna nomes de projetos da tabela projetos (ordenados A-Z)."""
    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("SELECT nome FROM projetos ORDER BY nome")
        ).fetchall()
    return [row.nome for row in rows]


def fetch_all_projetos() -> list[dict[str, Any]]:
    """Retorna todos os projetos com id, nome, descricao, criado_em."""
    with ENGINE.connect() as conn:
        rows = conn.execute(
            text("SELECT id, nome, descricao, criado_em FROM projetos ORDER BY nome")
        ).fetchall()
    return [dict(row._mapping) for row in rows]


def create_projeto(nome: str, descricao: str = "") -> None:
    with ENGINE.begin() as conn:
        conn.execute(
            text("INSERT INTO projetos (nome, descricao) VALUES (:nome, :descricao)"),
            {"nome": nome.strip().upper(), "descricao": descricao.strip()},
        )


def update_projeto(projeto_id: int, nome: str, descricao: str) -> None:
    with ENGINE.begin() as conn:
        conn.execute(
            text(
                "UPDATE projetos SET nome = :nome, descricao = :descricao WHERE id = :id"
            ),
            {"id": projeto_id, "nome": nome.strip().upper(), "descricao": descricao.strip()},
        )
        # Atualiza o campo texto em requisicoes para manter consistência
        conn.execute(
            text("UPDATE requisicoes SET projeto = :nome WHERE UPPER(TRIM(projeto)) = :old"),
            {"nome": nome.strip().upper(), "old": nome.strip().upper()},
        )


def delete_projeto(projeto_id: int, nome: str) -> None:
    with ENGINE.begin() as conn:
        conn.execute(text("DELETE FROM projetos WHERE id = :id"), {"id": projeto_id})
        conn.execute(
            text("UPDATE requisicoes SET projeto = NULL WHERE UPPER(TRIM(projeto)) = :nome"),
            {"nome": nome.strip().upper()},
        )


def fetch_requisicoes_por_projeto(projeto: str) -> list[dict[str, Any]]:
    query = "SELECT * FROM requisicoes WHERE UPPER(TRIM(projeto)) = :projeto ORDER BY id DESC"
    with ENGINE.connect() as conn:
        cursor = conn.execute(text(query), {"projeto": normalize_filter_value(projeto)})
        return [dict(row._mapping) for row in cursor.fetchall()]


def fetch_orcamentos_por_projeto(projeto: str) -> list[dict[str, Any]]:
    query = """
        SELECT
            o.*,
            r.projeto,
            r.item,
            r.empresa,
            r.requisicao
        FROM orcamentos o
        JOIN requisicoes r ON r.id = o.requisicao_id
        WHERE UPPER(TRIM(r.projeto)) = :projeto
        ORDER BY o.id DESC
    """
    with ENGINE.connect() as conn:
        cursor = conn.execute(text(query), {"projeto": normalize_filter_value(projeto)})
        return [dict(row._mapping) for row in cursor.fetchall()]
