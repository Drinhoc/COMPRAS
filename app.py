"""Streamlit app para controle de requisições de compras."""

from __future__ import annotations

import io
from datetime import date

import pandas as pd
import streamlit as st

from src import crud, excel_io, metrics
from src.auth import require_pin
from src.constants import COLUMN_ORDER, DISPLAY_NAMES, STATUS_LIST
from src.db import init_db


st.set_page_config(page_title="Controle de Compras", layout="wide")
init_db()

if not require_pin():
    st.stop()


def format_currency(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def render_filters() -> dict:
    st.sidebar.header("Filtros")
    empresas = crud.fetch_distinct("empresa")
    setores = crud.fetch_distinct("setor")
    fornecedores = crud.fetch_distinct("fornecedor")
    situacoes = STATUS_LIST

    empresa = st.sidebar.multiselect("Empresa", empresas, key="f_empresa")
    setor = st.sidebar.multiselect("Setor", setores, key="f_setor")
    fornecedor = st.sidebar.multiselect("Fornecedor", fornecedores, key="f_fornecedor")
    situacao = st.sidebar.multiselect("Situação", situacoes, key="f_situacao")

    data_sol = st.sidebar.date_input("Período Data Solicitação", value=(), key="f_data_solicitacao")
    data_compra = st.sidebar.date_input("Período Data Compra", value=(), key="f_data_compra")
    texto = st.sidebar.text_input("Busca texto", key="f_texto")

    filters = {
        "empresa": empresa,
        "setor": setor,
        "fornecedor": fornecedor,
        "situacao": situacao,
        "texto": texto.strip() or None,
    }

    if isinstance(data_sol, tuple) and len(data_sol) == 2:
        filters["data_solicitacao"] = (data_sol[0].isoformat(), data_sol[1].isoformat())
    if isinstance(data_compra, tuple) and len(data_compra) == 2:
        filters["data_compra"] = (data_compra[0].isoformat(), data_compra[1].isoformat())

    return filters


filters = render_filters()


def render_requisicao_form(prefix: str, data: dict | None = None) -> dict:
    data = data or {}
    col1, col2, col3 = st.columns(3)
    with col1:
        empresa = st.text_input("Empresa*", value=data.get("empresa", ""), key=f"{prefix}_empresa")
        setor = st.text_input("Setor", value=data.get("setor", ""), key=f"{prefix}_setor")
        requisicao = st.text_input("Requisição", value=data.get("requisicao", ""), key=f"{prefix}_requisicao")
        data_solicitacao = st.date_input(
            "Data Solicitação*",
            value=parse_date_input(data.get("data_solicitacao")) or date.today(),
            key=f"{prefix}_data_solicitacao",
        )
    with col2:
        sem_data_compra = st.checkbox(
            "Sem Data Compra",
            value=data.get("data_compra") in (None, ""),
            key=f"{prefix}_sem_data_compra",
        )
        data_compra = st.date_input(
            "Data Compra",
            value=(parse_date_input(data.get("data_compra")) or date.today()),
            key=f"{prefix}_data_compra",
            disabled=sem_data_compra,
        )
        fornecedor = st.text_input("Fornecedor", value=data.get("fornecedor", ""), key=f"{prefix}_fornecedor")
        qtde = st.number_input(
            "Qtde",
            min_value=0,
            step=1,
            value=to_int(data.get("qtde")),
            key=f"{prefix}_qtde",
        )
        item = st.text_input("Item*", value=data.get("item", ""), key=f"{prefix}_item")
    with col3:
        entrega = st.text_input("Entrega", value=data.get("entrega", ""), key=f"{prefix}_entrega")
        situacao = st.selectbox(
            "Situação",
            options=STATUS_LIST,
            index=STATUS_LIST.index(data.get("situacao")) if data.get("situacao") in STATUS_LIST else 0,
            key=f"{prefix}_situacao",
        )
        valor = st.text_input("Valor", value=to_str(data.get("valor")), key=f"{prefix}_valor")
        valor_desconto = st.text_input(
            "Valor Desconto",
            value=to_str(data.get("valor_desconto")),
            key=f"{prefix}_valor_desconto",
        )
        nf = st.text_input("NF", value=data.get("nf", ""), key=f"{prefix}_nf")
        observacao = st.text_area("Observação", value=data.get("observacao", ""), key=f"{prefix}_observacao")

    return {
        "empresa": empresa.strip(),
        "setor": setor.strip(),
        "requisicao": requisicao.strip(),
        "data_solicitacao": data_solicitacao.isoformat() if isinstance(data_solicitacao, date) else None,
        "data_compra": None if sem_data_compra else data_compra.isoformat(),
        "fornecedor": fornecedor.strip(),
        "qtde": qtde,
        "item": item.strip(),
        "entrega": entrega.strip(),
        "situacao": situacao,
        "valor": excel_io.parse_decimal(valor),
        "valor_desconto": excel_io.parse_decimal(valor_desconto),
        "nf": nf.strip(),
        "observacao": observacao.strip(),
    }


def parse_date_input(value: str | None) -> date | None:
    if not value:
        return None
    return pd.to_datetime(value).date()


def to_int(value: object | None) -> int:
    try:
        return int(value) if value is not None else 0
    except (ValueError, TypeError):
        return 0


def to_str(value: object | None) -> str:
    if value is None:
        return ""
    return str(value)


def validate_payload(payload: dict) -> list[str]:
    errors: list[str] = []
    if not payload["empresa"]:
        errors.append("Empresa é obrigatória.")
    if not payload["item"]:
        errors.append("Item é obrigatório.")
    if not payload["data_solicitacao"]:
        errors.append("Data Solicitação é obrigatória.")
    if payload["qtde"] is not None and payload["qtde"] < 0:
        errors.append("Qtde deve ser >= 0.")
    return errors


st.title("Sistema de Controle de Requisições")

aba_dashboard, aba_requisicoes, aba_importar = st.tabs([
    "Dashboard",
    "Requisições",
    "Importar",
])

with aba_dashboard:
    st.subheader("Métricas")
    df_metrics = metrics.fetch_dataframe(filters)
    total = metrics.total_gasto(df_metrics)
    st.metric("Total gasto", format_currency(total))

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Total por Empresa**")
        st.dataframe(metrics.total_por_empresa(df_metrics), use_container_width=True)
    with col2:
        st.markdown("**Total por Fornecedor**")
        st.dataframe(metrics.total_por_fornecedor(df_metrics), use_container_width=True)

    if st.button("Exportar Excel", key="export_dashboard"):
        bytes_xlsx = excel_io.export_to_excel(df_metrics[COLUMN_ORDER])
        st.download_button(
            label="Baixar arquivo",
            data=bytes_xlsx,
            file_name=f"requisicoes_{pd.Timestamp.now():%Y%m%d_%H%M%S}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_dashboard",
        )

with aba_requisicoes:
    st.subheader("Requisições")
    total_registros = crud.count_requisicoes(filters)
    page_size = st.selectbox("Registros por página", [10, 20, 50], index=1)
    total_paginas = max(1, (total_registros + page_size - 1) // page_size)
    pagina = st.number_input("Página", min_value=1, max_value=total_paginas, value=1)
    offset = (pagina - 1) * page_size

    registros = crud.fetch_requisicoes(filters, limit=page_size, offset=offset)
    df_view = pd.DataFrame(registros)
    if not df_view.empty:
        for col in ["data_solicitacao", "data_compra"]:
            if col in df_view.columns:
                df_view[col] = df_view[col].apply(excel_io.format_date_display)
        df_view = df_view.rename(columns=DISPLAY_NAMES)
    st.dataframe(df_view, use_container_width=True)

    st.markdown("### Editar requisição")
    if registros:
        selected_id = st.selectbox("Selecione o ID", [row["id"] for row in registros])
        selecionado = crud.get_by_id(selected_id)
        if selecionado:
            with st.form("editar_form"):
                payload = render_requisicao_form("edit", selecionado)
                submitted = st.form_submit_button("Salvar alterações")
                if submitted:
                    errors = validate_payload(payload)
                    if errors:
                        for err in errors:
                            st.error(err)
                    else:
                        crud.update_requisicao(selected_id, payload)
                        st.success("Requisição atualizada.")
                        st.experimental_rerun()
    else:
        st.info("Nenhum registro encontrado com os filtros atuais.")

    st.markdown("### Nova requisição")
    with st.form("novo_form"):
        payload = render_requisicao_form("novo")
        submitted = st.form_submit_button("Criar requisição")
        if submitted:
            errors = validate_payload(payload)
            if errors:
                for err in errors:
                    st.error(err)
            else:
                crud.create_requisicao(payload)
                st.success("Requisição criada.")
                st.experimental_rerun()

    if st.button("Exportar Excel", key="export_requisicoes"):
        df_export = metrics.fetch_dataframe(filters)
        bytes_xlsx = excel_io.export_to_excel(df_export[COLUMN_ORDER])
        st.download_button(
            label="Baixar arquivo",
            data=bytes_xlsx,
            file_name=f"requisicoes_{pd.Timestamp.now():%Y%m%d_%H%M%S}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_requisicoes",
        )

with aba_importar:
    st.subheader("Importar Excel")
    upload = st.file_uploader("Selecione o arquivo .xlsx", type=["xlsx"])
    if upload:
        file_bytes = upload.getvalue()
        excel_file = pd.ExcelFile(io.BytesIO(file_bytes))
        sheets = excel_file.sheet_names
        sheet = st.selectbox("Selecione a planilha", ["(Primeira)"] + sheets)
        sheet_name = None if sheet == "(Primeira)" else sheet

        if st.button("Importar"):
            df_raw = excel_io.load_excel(io.BytesIO(file_bytes), sheet_name=sheet_name)
            total_before = len(df_raw)
            df_norm = excel_io.normalize_dataframe(df_raw)
            total_after = len(df_norm)
            registros = excel_io.dataframe_to_records(df_norm)
            quantidade = len(registros)
            if quantidade:
                from src.db import insert_many

                insert_many(registros)
                st.success(f"{quantidade} registros importados.")
                st.warning("Importação não remove duplicatas automaticamente.")
                if total_after < total_before:
                    st.info(
                        f"{total_before - total_after} linhas foram ignoradas por não terem Item (obrigatório)."
                    )
            else:
                st.info("Nenhum registro encontrado para importar.")
