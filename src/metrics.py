"""Métricas de compras."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from .crud import build_filters
from .db import ENGINE


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
    df["total"] = df["valor"].fillna(0) - df["valor_desconto"].fillna(0)
    return df.groupby("empresa", dropna=False)["total"].sum().reset_index()


def total_por_fornecedor(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["fornecedor", "total"])
    df = df.copy()
    df["total"] = df["valor"].fillna(0) - df["valor_desconto"].fillna(0)
    return df.groupby("fornecedor", dropna=False)["total"].sum().reset_index()
