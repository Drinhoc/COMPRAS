"""Streamlit app para controle de requisições de compras."""

from __future__ import annotations

import io
import os
from datetime import date

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode

from src import crud, excel_io, metrics
from src.auth import require_pin
from src.constants import COLUMN_ORDER, DISPLAY_NAMES, STATUS_LIST
from src.db import get_database_url, init_db, is_sqlite_url


st.set_page_config(page_title="Controle de Compras", layout="wide")
database_url = get_database_url()
if is_sqlite_url(database_url):
    st.warning(
        "Banco atual: SQLite local. Em deploy (Railway) isso pode resetar a cada reinício. "
        "Configure a variável DATABASE_URL do Postgres do Railway para persistência."
    )
    if os.getenv("RAILWAY_ENVIRONMENT"):
        st.error("DATABASE_URL não configurada no Railway. O banco não é persistente.")
        st.stop()
init_db()

if not require_pin():
    st.stop()


def format_currency(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def render_filters() -> dict:
    st.sidebar.header("Filtros")
    preset = st.sidebar.radio(
        "Visualização rápida",
        ["Todos", "Pendentes", "Comprados", "Entregues"],
        horizontal=False,
        key="f_preset",
    )

    preset_map = {
        "Todos": [],
        "Pendentes": ["Solicitado"],
        "Comprados": ["Comprado"],
        "Entregues": ["Entregue"],
    }

    empresas = crud.fetch_distinct("empresa")
    setores = crud.fetch_distinct("setor")
    fornecedores = crud.fetch_distinct("fornecedor")
    situacoes = STATUS_LIST

    with st.sidebar.expander("Filtros avançados", expanded=False):
        empresa = st.multiselect("Empresa", empresas, key="f_empresa")
        setor = st.multiselect("Setor", setores, key="f_setor")
        fornecedor = st.multiselect("Fornecedor", fornecedores, key="f_fornecedor")
        situacao = st.multiselect("Situação", situacoes, key="f_situacao")
        data_sol = st.date_input("Período Data Solicitação", value=(), key="f_data_solicitacao")
        data_compra = st.date_input("Período Data Compra", value=(), key="f_data_compra")
        texto = st.text_input("Busca texto", key="f_texto")

    situacoes_aplicadas = situacao or preset_map[preset]

    filters = {
        "empresa": empresa,
        "setor": setor,
        "fornecedor": fornecedor,
        "situacao": situacoes_aplicadas,
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


def highlight_status(df: pd.DataFrame) -> pd.DataFrame:
    colors = []
    for status_value in df.get("situacao", []):
        status = str(status_value or "").strip().upper()
        if status in {"CONCLUÍDO", "ENTREGUE"}:
            color = "#D1F7C4"
        elif status == "COMPRADO":
            color = "#FFF3BF"
        else:
            color = "#FFD6D6"
        colors.append([f"background-color: {color}"] * len(df.columns))
    return pd.DataFrame(colors, index=df.index, columns=df.columns)


def build_payload_from_row(row: pd.Series, original: pd.Series) -> dict:
    payload = {col: original.get(col) for col in COLUMN_ORDER}
    payload.update(
        {
            "empresa": excel_io.normalize_text(row.get("empresa")),
            "setor": excel_io.normalize_text(row.get("setor")),
            "requisicao": str(row.get("requisicao") or "").strip(),
            "data_solicitacao": excel_io.parse_date(row.get("data_solicitacao")),
            "data_compra": excel_io.parse_date(row.get("data_compra")),
            "fornecedor": excel_io.normalize_text(row.get("fornecedor")),
            "qtde": excel_io.parse_int(row.get("qtde")),
            "item": str(row.get("item") or "").strip(),
            "entrega": str(row.get("entrega") or "").strip(),
            "situacao": excel_io.normalize_text(row.get("situacao")),
            "valor": excel_io.parse_decimal(row.get("valor")),
            "valor_desconto": excel_io.parse_decimal(row.get("valor_desconto")),
            "nf": str(row.get("nf") or "").strip() or None,
            "observacao": str(row.get("observacao") or "").strip(),
        }
    )
    return payload


st.title("Sistema de Controle de Requisições")

aba_dashboard, aba_requisicoes, aba_pendentes, aba_importar = st.tabs([
    "Dashboard",
    "Requisições",
    "Pendentes de Aprovação",
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
    if st.button("Atualizar tabela"):
        st.experimental_rerun()

    total_registros = crud.count_requisicoes(filters)
    page_size = st.selectbox("Registros por página", [10, 20, 50], index=1)
    total_paginas = max(1, (total_registros + page_size - 1) // page_size)
    pagina = st.number_input("Página", min_value=1, max_value=total_paginas, value=1)
    offset = (pagina - 1) * page_size

    registros = crud.fetch_requisicoes(filters, limit=page_size, offset=offset)
    df_edit = pd.DataFrame(registros)

    if not df_edit.empty:
        left_col, right_col = st.columns([1.1, 1.9])

        with left_col:
            st.markdown("### Lista de requisições")
            grid_df = df_edit[["id", "empresa", "item", "situacao", "fornecedor", "data_solicitacao"]].copy()
            gb = GridOptionsBuilder.from_dataframe(grid_df)
            gb.configure_default_column(editable=False, filter=True, sortable=True, resizable=True)
            gb.configure_selection("single", use_checkbox=False)
            gb.configure_grid_options(
                suppressRowClickSelection=False,
                rowSelection="single",
                getRowStyle=JsCode(
                    """
                    function(params) {
                        const status = (params.data.situacao || '').toString().trim().toUpperCase();
                        if (status === 'ENTREGUE') return {backgroundColor: '#D1F7C4'};
                        if (status === 'COMPRADO') return {backgroundColor: '#FFF3BF'};
                        return {backgroundColor: '#FFD6D6'};
                    }
                    """
                ),
            )
            grid = AgGrid(
                grid_df,
                gridOptions=gb.build(),
                fit_columns_on_grid_load=True,
                allow_unsafe_jscode=True,
                theme="streamlit",
                key="lista_requisicoes",
                height=470,
            )
            selected_rows = grid.get("selected_rows", [])
            if selected_rows:
                st.session_state.selected_req_id = int(selected_rows[0]["id"])
            elif "selected_req_id" not in st.session_state:
                st.session_state.selected_req_id = int(grid_df.iloc[0]["id"])

            st.caption("Clique em uma linha para abrir o detalhe ao lado.")

        selected_req_id = int(st.session_state["selected_req_id"])
        req_data = crud.get_by_id(selected_req_id)

        with right_col:
            st.markdown(f"### Detalhe da requisição #{selected_req_id}")
            req_tabs = st.tabs(["Resumo", "Orçamentos", "Anexos", "Aprovação", "Histórico"])

            with req_tabs[0]:
                if req_data:
                    resumo_df = pd.DataFrame(
                        [
                            {"Campo": DISPLAY_NAMES.get(col, col), "Valor": req_data.get(col)}
                            for col in COLUMN_ORDER
                        ]
                    )
                    st.dataframe(resumo_df, use_container_width=True, hide_index=True)
                with st.form(f"edit_req_{selected_req_id}"):
                    payload = render_requisicao_form(f"edit_{selected_req_id}", req_data)
                    submitted_edit = st.form_submit_button("Salvar dados da requisição")
                    if submitted_edit:
                        errors = validate_payload(payload)
                        if errors:
                            for err in errors:
                                st.error(err)
                        else:
                            crud.update_requisicao(selected_req_id, payload)
                            st.success("Requisição atualizada.")
                            st.experimental_rerun()

                st.markdown("#### Excluir requisição")
                if st.button("Excluir requisição selecionada", key=f"btn_del_req_{selected_req_id}"):
                    st.session_state.delete_id_pending = selected_req_id
                if st.session_state.get("delete_id_pending") == selected_req_id:
                    st.warning(f"Confirma excluir a requisição #{selected_req_id}?")
                    c_confirm, c_cancel = st.columns(2)
                    with c_confirm:
                        if st.button("Confirmar exclusão", key=f"confirm_del_req_{selected_req_id}"):
                            crud.delete_requisicao(selected_req_id)
                            st.session_state.pop("delete_id_pending", None)
                            st.session_state.pop("selected_req_id", None)
                            st.success("Requisição excluída.")
                            st.experimental_rerun()
                    with c_cancel:
                        if st.button("Cancelar", key=f"cancel_del_req_{selected_req_id}"):
                            st.session_state.pop("delete_id_pending", None)

            with req_tabs[1]:
                st.caption("Cadastre e compare orçamentos da requisição selecionada.")
                orcs = crud.list_orcamentos(selected_req_id)
                st.dataframe(pd.DataFrame(orcs), use_container_width=True)
                with st.form(f"form_orcamento_{selected_req_id}"):
                    c1, c2 = st.columns(2)
                    fornecedor_orc = c1.text_input("Fornecedor")
                    valor_orc = c1.text_input("Valor")
                    prazo_orc = c2.date_input("Prazo Entrega", value=None)
                    cond_orc = c2.text_input("Condições de Pagamento")
                    status_orc = st.selectbox("Status orçamento", ["RECEBIDO", "APROVADO", "REJEITADO"])
                    obs_orc = st.text_area("Observação orçamento")
                    if st.form_submit_button("Adicionar orçamento"):
                        crud.create_orcamento(
                            {
                                "requisicao_id": selected_req_id,
                                "fornecedor": excel_io.normalize_text(fornecedor_orc),
                                "valor": excel_io.parse_decimal(valor_orc),
                                "prazo_entrega": prazo_orc.isoformat() if prazo_orc else None,
                                "condicoes_pagamento": cond_orc.strip(),
                                "status_orcamento": status_orc,
                                "observacao": obs_orc.strip(),
                            }
                        )
                        st.success("Orçamento adicionado.")
                        st.experimental_rerun()
                if orcs:
                    del_orc = st.selectbox(
                        "Excluir orçamento (ID)",
                        [o["id"] for o in orcs],
                        key=f"del_orc_{selected_req_id}",
                    )
                    if st.button("Excluir orçamento", key=f"btn_del_orc_{selected_req_id}"):
                        crud.delete_orcamento(int(del_orc))
                        st.success("Orçamento excluído.")
                        st.experimental_rerun()

            with req_tabs[2]:
                st.caption("Anexos ficam no próprio banco (BLOB) por enquanto.")
                anexos = crud.list_anexos(selected_req_id)
                st.dataframe(pd.DataFrame(anexos), use_container_width=True)
                up = st.file_uploader("Enviar anexo", key=f"anexo_{selected_req_id}")
                tipo_anexo = st.selectbox(
                    "Tipo",
                    ["orcamento", "nf", "contrato", "outros"],
                    key=f"tipo_{selected_req_id}",
                )
                if st.button(f"Salvar anexo", key=f"btn_save_anexo_{selected_req_id}") and up is not None:
                    crud.create_anexo(
                        {
                            "requisicao_id": selected_req_id,
                            "orcamento_id": None,
                            "tipo": tipo_anexo,
                            "nome_arquivo": up.name,
                            "mime_type": up.type,
                            "conteudo": up.getvalue(),
                            "uploaded_by": "gestor",
                        }
                    )
                    st.success("Anexo salvo no banco.")
                    st.experimental_rerun()
                if anexos:
                    anexo_id = st.selectbox(
                        "Baixar/Excluir anexo (ID)",
                        [a["id"] for a in anexos],
                        key=f"anexo_ops_{selected_req_id}",
                    )
                    anexo = crud.get_anexo_conteudo(int(anexo_id))
                    if anexo:
                        st.download_button(
                            "Baixar anexo",
                            data=anexo["conteudo"],
                            file_name=anexo["nome_arquivo"],
                            mime=anexo.get("mime_type") or "application/octet-stream",
                            key=f"dl_{selected_req_id}_{anexo_id}",
                        )
                    if st.button("Excluir anexo", key=f"del_anexo_{selected_req_id}"):
                        crud.delete_anexo(int(anexo_id))
                        st.success("Anexo excluído.")
                        st.experimental_rerun()

            with req_tabs[3]:
                st.caption("Registre aprovações/reprovações e comentários do gestor.")
                aps = crud.list_aprovacoes(selected_req_id)
                st.dataframe(pd.DataFrame(aps), use_container_width=True)
                c1, c2 = st.columns(2)
                acao = c1.selectbox(
                    "Ação",
                    ["APROVADO", "REPROVADO", "DEVOLVIDO", "COMENTÁRIO"],
                    key=f"acao_{selected_req_id}",
                )
                aprovador = c2.text_input("Aprovador", value="GESTOR", key=f"apr_{selected_req_id}")
                comentario = st.text_area("Comentário", key=f"obs_apr_{selected_req_id}")
                if st.button("Registrar ação", key=f"btn_apr_{selected_req_id}"):
                    crud.create_aprovacao(
                        {
                            "requisicao_id": selected_req_id,
                            "acao": acao,
                            "comentario": comentario.strip(),
                            "aprovador": aprovador.strip() or "GESTOR",
                        }
                    )
                    if acao == "APROVADO" and req_data:
                        req_data["situacao"] = "Comprado"
                        crud.update_requisicao(selected_req_id, req_data)
                    st.success("Ação registrada.")
                    st.experimental_rerun()

            with req_tabs[4]:
                st.caption("Linha do tempo de ações e documentos.")
                historico: list[dict] = []
                for aprov in crud.list_aprovacoes(selected_req_id):
                    historico.append(
                        {
                            "Data": aprov.get("created_at"),
                            "Tipo": "Aprovação",
                            "Evento": aprov.get("acao"),
                            "Responsável": aprov.get("aprovador"),
                            "Detalhe": aprov.get("comentario"),
                        }
                    )
                for anexo in crud.list_anexos(selected_req_id):
                    historico.append(
                        {
                            "Data": anexo.get("uploaded_at"),
                            "Tipo": "Anexo",
                            "Evento": anexo.get("tipo"),
                            "Responsável": anexo.get("uploaded_by"),
                            "Detalhe": anexo.get("nome_arquivo"),
                        }
                    )
                for orc in crud.list_orcamentos(selected_req_id):
                    historico.append(
                        {
                            "Data": orc.get("created_at"),
                            "Tipo": "Orçamento",
                            "Evento": orc.get("status_orcamento"),
                            "Responsável": orc.get("fornecedor"),
                            "Detalhe": f"Valor: {orc.get('valor')}",
                        }
                    )
                hist_df = pd.DataFrame(historico)
                if hist_df.empty:
                    st.info("Sem histórico para esta requisição.")
                else:
                    hist_df["Data"] = pd.to_datetime(hist_df["Data"], errors="coerce")
                    hist_df = hist_df.sort_values("Data", ascending=False)
                    st.dataframe(hist_df, use_container_width=True, hide_index=True)

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

with aba_pendentes:
    st.subheader("Pendentes de Aprovação")
    pending_filters = dict(filters)
    pending_filters["situacao"] = ["Solicitado"]
    pendentes = crud.fetch_requisicoes(pending_filters, limit=500, offset=0)
    if not pendentes:
        st.success("Não há requisições pendentes no momento.")
    else:
        st.dataframe(pd.DataFrame(pendentes), use_container_width=True)

with aba_importar:
    st.subheader("Importar Excel")
    upload = st.file_uploader("Selecione o arquivo .xlsx", type=["xlsx"], key="upload_excel")
    if upload is not None:
        st.session_state.import_file_bytes = upload.getvalue()
        st.session_state.import_file_name = upload.name
    file_bytes = st.session_state.get("import_file_bytes")
    if file_bytes:
        excel_file = pd.ExcelFile(io.BytesIO(file_bytes))
        sheets = excel_file.sheet_names
        sheet = st.selectbox("Selecione a planilha", ["(Primeira)"] + sheets)
        sheet_name = None if sheet == "(Primeira)" else sheet

        st.caption(f"Arquivo atual: {st.session_state.get('import_file_name', 'upload')} ")
        if st.button("Limpar arquivo carregado"):
            st.session_state.pop("import_file_bytes", None)
            st.session_state.pop("import_file_name", None)
            st.experimental_rerun()

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
                        "Linhas ignoradas sem Empresa, Item ou Data Solicitação (campos obrigatórios). "
                        f"Total: {total_before - total_after}."
                    )
            else:
                st.info("Nenhum registro encontrado para importar.")
