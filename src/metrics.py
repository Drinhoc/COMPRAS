"""Métricas de compras."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from .crud import build_filters
from .db import ENGINE
from .excel_io import normalize_text

# Statuses que representam carteira em aberto (não finalizados)
SITUACOES_ABERTAS = {"solicitado", "cotação", "cotacao", "aprovação", "aprovacao"}


def fetch_dataframe(filters: dict) -> pd.DataFrame:
    where_clause, params = build_filters(filters)
    query = text(f"SELECT * FROM requisicoes{where_clause}")
    with ENGINE.connect() as conn:
        df = pd.read_sql_query(query, conn, params=params)
    return df


def total_gasto(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    valor = df["valor"].fillna(0)
    desconto = df["valor_desconto"].fillna(0)
    return float((valor - desconto).sum())


def total_por_empresa(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["empresa", "total"])
    df = df.copy()
    df["empresa"] = df["empresa"].apply(normalize_text)
    df["total"] = df["valor"].fillna(0) - df["valor_desconto"].fillna(0)
    return df.groupby("empresa", dropna=False)["total"].sum().reset_index()


def total_por_fornecedor(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["fornecedor", "total"])
    df = df.copy()
    df["total"] = df["valor"].fillna(0) - df["valor_desconto"].fillna(0)
    return df.groupby("fornecedor", dropna=False)["total"].sum().reset_index()


def valor_em_aberto(df: pd.DataFrame) -> float:
    """Soma de valor para requisições ainda não finalizadas (Solicitado/Cotação/Aprovação)."""
    if df.empty:
        return 0.0
    mask = df["situacao"].fillna("").str.lower().str.strip().isin(SITUACOES_ABERTAS)
    return float(df.loc[mask, "valor"].fillna(0).sum())


def ticket_medio(df: pd.DataFrame) -> float:
    """Valor médio por requisição (ignora linhas sem valor)."""
    if df.empty:
        return 0.0
    valores = df["valor"].dropna()
    valores = valores[valores > 0]
    return float(valores.mean()) if not valores.empty else 0.0


def tempo_medio_atendimento(df: pd.DataFrame) -> float:
    """Média de dias entre data_solicitacao e data_compra (apenas onde ambas existem)."""
    if df.empty:
        return 0.0
    d = df.copy()
    d["data_solicitacao"] = pd.to_datetime(d["data_solicitacao"], errors="coerce")
    d["data_compra"] = pd.to_datetime(d["data_compra"], errors="coerce")
    validos = d.dropna(subset=["data_solicitacao", "data_compra"])
    if validos.empty:
        return 0.0
    dias = (validos["data_compra"] - validos["data_solicitacao"]).dt.days
    dias = dias[dias >= 0]
    return float(dias.mean()) if not dias.empty else 0.0


def contagem_por_situacao(df: pd.DataFrame) -> pd.DataFrame:
    """Contagem e valor total agrupados por situação."""
    if df.empty:
        return pd.DataFrame(columns=["situacao", "quantidade", "valor_total"])
    d = df.copy()
    d["valor_total"] = d["valor"].fillna(0)
    result = (
        d.groupby("situacao", dropna=False)
        .agg(quantidade=("id", "count"), valor_total=("valor_total", "sum"))
        .reset_index()
    )
    return result.sort_values("valor_total", ascending=False)


def evolucao_mensal(df: pd.DataFrame, date_col: str = "data_solicitacao") -> pd.DataFrame:
    """Agrega requisições por mês (YYYY-MM)."""
    if df.empty:
        return pd.DataFrame(columns=["mes", "quantidade", "valor_total"])
    d = df.copy()
    d["_dt"] = pd.to_datetime(d[date_col], errors="coerce")
    d = d.dropna(subset=["_dt"])
    if d.empty:
        return pd.DataFrame(columns=["mes", "quantidade", "valor_total"])
    d["mes"] = d["_dt"].dt.to_period("M").astype(str)
    result = (
        d.groupby("mes")
        .agg(quantidade=("id", "count"), valor_total=("valor", "sum"))
        .reset_index()
        .sort_values("mes")
    )
    result["valor_total"] = result["valor_total"].fillna(0)
    return result


def top_fornecedores(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Top N fornecedores por valor total."""
    if df.empty:
        return pd.DataFrame(columns=["fornecedor", "quantidade", "valor_total"])
    d = df.copy()
    d["valor_total"] = d["valor"].fillna(0)
    result = (
        d.groupby("fornecedor", dropna=False)
        .agg(quantidade=("id", "count"), valor_total=("valor_total", "sum"))
        .reset_index()
        .sort_values("valor_total", ascending=False)
        .head(n)
    )
    return result


def pareto_fornecedores(df: pd.DataFrame) -> pd.DataFrame:
    """Análise de Pareto de fornecedores: valor acumulado % do gasto total."""
    if df.empty:
        return pd.DataFrame(columns=["fornecedor", "valor_total", "percentual", "acumulado"])
    d = df.copy()
    d["valor_total"] = d["valor"].fillna(0)
    result = (
        d.groupby("fornecedor", dropna=False)["valor_total"]
        .sum()
        .reset_index()
        .sort_values("valor_total", ascending=False)
    )
    total = result["valor_total"].sum()
    if total == 0:
        result["percentual"] = 0.0
        result["acumulado"] = 0.0
        return result
    result["percentual"] = result["valor_total"] / total * 100
    result["acumulado"] = result["percentual"].cumsum()
    return result


def metricas_por_empresa(df: pd.DataFrame) -> pd.DataFrame:
    """Empresa → quantidade, valor_total, ticket_medio."""
    if df.empty:
        return pd.DataFrame(columns=["empresa", "quantidade", "valor_total", "ticket_medio"])
    d = df.copy()
    d["valor"] = d["valor"].fillna(0)
    result = (
        d.groupby("empresa", dropna=False)
        .agg(quantidade=("id", "count"), valor_total=("valor", "sum"))
        .reset_index()
        .sort_values("valor_total", ascending=False)
    )
    result["ticket_medio"] = result.apply(
        lambda r: r["valor_total"] / r["quantidade"] if r["quantidade"] > 0 else 0.0, axis=1
    )
    return result


def metricas_por_projeto(df: pd.DataFrame) -> pd.DataFrame:
    """Projeto → quantidade, valor_total."""
    if df.empty:
        return pd.DataFrame(columns=["projeto", "quantidade", "valor_total"])
    d = df.copy()
    d["valor"] = d["valor"].fillna(0)
    result = (
        d.groupby("projeto", dropna=False)
        .agg(quantidade=("id", "count"), valor_total=("valor", "sum"))
        .reset_index()
        .sort_values("valor_total", ascending=False)
    )
    return result


def distribuicao_tempo(df: pd.DataFrame) -> pd.Series:
    """Série de dias entre solicitação e compra (para histograma)."""
    if df.empty:
        return pd.Series(dtype=float)
    d = df.copy()
    d["data_solicitacao"] = pd.to_datetime(d["data_solicitacao"], errors="coerce")
    d["data_compra"] = pd.to_datetime(d["data_compra"], errors="coerce")
    validos = d.dropna(subset=["data_solicitacao", "data_compra"])
    if validos.empty:
        return pd.Series(dtype=float)
    dias = (validos["data_compra"] - validos["data_solicitacao"]).dt.days
    return dias[dias >= 0].reset_index(drop=True)


def tempo_por_fornecedor(df: pd.DataFrame) -> pd.DataFrame:
    """Tempo médio de atendimento por fornecedor."""
    if df.empty:
        return pd.DataFrame(columns=["fornecedor", "tempo_medio_dias", "quantidade"])
    d = df.copy()
    d["data_solicitacao"] = pd.to_datetime(d["data_solicitacao"], errors="coerce")
    d["data_compra"] = pd.to_datetime(d["data_compra"], errors="coerce")
    d = d.dropna(subset=["data_solicitacao", "data_compra", "fornecedor"])
    if d.empty:
        return pd.DataFrame(columns=["fornecedor", "tempo_medio_dias", "quantidade"])
    d["dias"] = (d["data_compra"] - d["data_solicitacao"]).dt.days
    d = d[d["dias"] >= 0]
    result = (
        d.groupby("fornecedor")
        .agg(tempo_medio_dias=("dias", "mean"), quantidade=("id", "count"))
        .reset_index()
        .sort_values("tempo_medio_dias")
    )
    result["tempo_medio_dias"] = result["tempo_medio_dias"].round(1)
    return result
