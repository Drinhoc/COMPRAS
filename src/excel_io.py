"""Importação e exportação de Excel."""

from __future__ import annotations

import io
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from .constants import COLUMN_MAP, COLUMN_ORDER, DISPLAY_NAMES


def normalize_header(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace(" ", "_")
    text = text.replace("-", "_")
    return text


def parse_decimal(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(".", "").replace(",", ".") if "," in text else text
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, date)):
        return value.date().isoformat() if hasattr(value, "date") else value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date().isoformat()


def normalize_nf(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return str(int(value))
        return str(value)
    text = str(value).strip()
    return text or None


def load_excel(file: io.BytesIO, sheet_name: str | None = None) -> pd.DataFrame:
    df = pd.read_excel(file, sheet_name=sheet_name, header=0)
    if all(str(col).lower().startswith("unnamed") for col in df.columns):
        df = pd.read_excel(file, sheet_name=sheet_name, header=1)
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
    return df


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    mapped = {}
    for col in df.columns:
        normalized = normalize_header(col)
        mapped[col] = COLUMN_MAP.get(normalized, normalized)
    df = df.rename(columns=mapped)
    df = df[[col for col in df.columns if col in COLUMN_ORDER]]

    for col in COLUMN_ORDER:
        if col not in df.columns:
            df[col] = None

    df["data_solicitacao"] = df["data_solicitacao"].apply(parse_date)
    df["data_compra"] = df["data_compra"].apply(parse_date)
    df["valor"] = df["valor"].apply(parse_decimal)
    df["valor_desconto"] = df["valor_desconto"].apply(parse_decimal)
    df["qtde"] = df["qtde"].apply(parse_int)
    df["nf"] = df["nf"].apply(normalize_nf)

    df = filter_required_fields(df)

    return df[COLUMN_ORDER]


def dataframe_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    normalized = df.where(pd.notna(df), None)
    records = normalized.to_dict(orient="records")
    return [_normalize_record_values(record) for record in records]


def export_to_excel(df: pd.DataFrame) -> bytes:
    df_export = df.copy()
    for col in ["data_solicitacao", "data_compra"]:
        if col in df_export.columns:
            df_export[col] = df_export[col].apply(format_date_display)
    df_export = df_export.rename(columns=DISPLAY_NAMES)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_export.to_excel(writer, index=False, sheet_name="Requisicoes")
    return output.getvalue()


def format_date_display(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%d/%m/%Y")


def _normalize_record_values(record: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in record.items():
        if value is None or pd.isna(value):
            normalized[key] = None
            continue
        if isinstance(value, (pd.Timestamp, np.datetime64, datetime, date)):
            parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
            normalized[key] = None if pd.isna(parsed) else parsed.date().isoformat()
            continue
        if isinstance(value, Decimal):
            normalized[key] = float(value)
            continue
        if isinstance(value, np.generic):
            normalized[key] = value.item()
            continue
        normalized[key] = value
    return normalized


def parse_int(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text.replace(",", ".")))
    except ValueError:
        return None


def filter_required_fields(df: pd.DataFrame) -> pd.DataFrame:
    if "item" not in df.columns:
        return df
    item_series = df["item"].astype(str)
    mask = df["item"].notna() & item_series.str.strip().ne("")
    return df.loc[mask].copy()
