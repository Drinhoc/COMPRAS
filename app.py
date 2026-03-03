"""Streamlit app para controle de requisições de compras."""

from __future__ import annotations

import io
import os
from datetime import date

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
from st_aggrid.shared import GridUpdateMode

from src import crud, excel_io, metrics
from src.constants import COLUMN_ORDER, DISPLAY_NAMES, STATUS_LIST
from src.db import get_database_url, init_db, is_sqlite_url


st.set_page_config(page_title="Controle de Compras", layout="wide")
st.markdown(
    """
    <style>
        [data-testid="stSidebar"] {
            min-width: 400px;
            max-width: 400px;
        }
        [data-testid="metric-container"] {
            border: 1px solid #ddd;
            border-radius: 10px;
            padding: 10px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)
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


HAS_ST_DIALOG = callable(getattr(st, "dialog", None))


def build_dialog_decorator(title: str, width: str = "large"):
    dialog_api = getattr(st, "dialog", None)
    if callable(dialog_api):
        return dialog_api(title, width=width)

    def passthrough(fn):
        return fn

    return passthrough



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
    projetos = crud.fetch_distinct("projeto")
    fornecedores = crud.fetch_distinct("fornecedor")
    situacoes = STATUS_LIST

    with st.sidebar.expander("Filtros avançados", expanded=False):
        empresa = st.multiselect("Empresa", empresas, key="f_empresa")
        setor = st.multiselect("Setor", setores, key="f_setor")
        projeto = st.multiselect("Projeto", projetos, key="f_projeto")
        fornecedor = st.multiselect("Fornecedor", fornecedores, key="f_fornecedor")
        situacao = st.multiselect("Situação", situacoes, key="f_situacao")
        data_sol = st.date_input("Período Data Solicitação", value=(), key="f_data_solicitacao")
        data_compra = st.date_input("Período Data Compra", value=(), key="f_data_compra")
        texto = st.text_input("Busca texto", key="f_texto")

    situacoes_aplicadas = situacao or preset_map[preset]

    filters = {
        "empresa": empresa,
        "setor": setor,
        "projeto": projeto,
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

st.sidebar.markdown("---")
with st.sidebar.expander("Admin (MVP)", expanded=False):
    st.caption("Use apenas em fase de criação/homologação.")
    st.warning("Essa ação apaga TODAS as requisições, orçamentos, anexos e aprovações.")
    confirm_reset = st.checkbox("Entendo que essa ação é irreversível", key="confirm_reset_all")
    confirm_text = st.text_input(
        "Para confirmar, digite LIMPAR TUDO",
        key="confirm_reset_all_text",
        placeholder="LIMPAR TUDO",
    )
    if st.button("🗑️ Limpar base inteira", key="btn_reset_all_data"):
        if not confirm_reset or confirm_text.strip().upper() != "LIMPAR TUDO":
            st.error("Confirmação inválida. Marque a caixa e digite exatamente: LIMPAR TUDO")
        else:
            crud.delete_all_data()
            st.session_state.pop("selected_req_id", None)
            st.session_state.pop("delete_id_pending", None)
            st.success("Base limpa com sucesso.")
            st.rerun()


def render_requisicao_form(prefix: str, data: dict | None = None) -> dict:
    data = data or {}

    projetos_existentes = crud.list_projetos()
    empresas_existentes = crud.fetch_distinct("empresa")
    setores_existentes = crud.fetch_distinct("setor")

    projeto_padrao = str(data.get("projeto") or "").strip().upper()
    empresa_padrao = str(data.get("empresa") or "").strip().upper()
    setor_padrao = str(data.get("setor") or "").strip().upper()

    projeto_opcoes = ["(Sem projeto)"] + projetos_existentes + ["+ Novo projeto"]
    empresa_opcoes = empresas_existentes + ["+ Nova empresa"] if empresas_existentes else ["+ Nova empresa"]
    setor_opcoes = setores_existentes + ["+ Novo setor"] if setores_existentes else ["+ Novo setor"]

    default_projeto = projeto_padrao if projeto_padrao in projetos_existentes else ("+ Novo projeto" if projeto_padrao else "(Sem projeto)")
    default_empresa = empresa_padrao if empresa_padrao in empresas_existentes else "+ Nova empresa"
    default_setor = setor_padrao if setor_padrao in setores_existentes else "+ Novo setor"

    col1, col2, col3 = st.columns(3)
    with col1:
        empresa_sel = st.selectbox("Empresa*", options=empresa_opcoes, index=empresa_opcoes.index(default_empresa), key=f"{prefix}_empresa_sel")
        empresa_nova = st.text_input(
            "Nova empresa",
            value="" if default_empresa != "+ Nova empresa" else empresa_padrao,
            key=f"{prefix}_empresa_nova",
        )

        setor_sel = st.selectbox("Setor", options=setor_opcoes, index=setor_opcoes.index(default_setor), key=f"{prefix}_setor_sel")
        setor_novo = st.text_input(
            "Novo setor",
            value="" if default_setor != "+ Novo setor" else setor_padrao,
            key=f"{prefix}_setor_novo",
        )

        requisicao = st.text_input("Requisição", value=data.get("requisicao", ""), key=f"{prefix}_requisicao")
        data_solicitacao = st.date_input(
            "Data Solicitação*",
            value=parse_date_input(data.get("data_solicitacao")) or date.today(),
            key=f"{prefix}_data_solicitacao",
        )

    with col2:
        projeto_escolhido = st.selectbox(
            "Projeto",
            options=projeto_opcoes,
            index=projeto_opcoes.index(default_projeto),
            key=f"{prefix}_projeto_sel",
            help="Selecione um projeto existente ou crie um novo.",
        )
        projeto_novo_default = projeto_padrao if default_projeto == "+ Novo projeto" else ""
        projeto_novo = st.text_input("Novo projeto", value=projeto_novo_default, key=f"{prefix}_projeto_novo")

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

    with col3:
        qtde = st.number_input("Qtde", min_value=0, step=1, value=to_int(data.get("qtde")), key=f"{prefix}_qtde")
        item = st.text_input("Item*", value=data.get("item", ""), key=f"{prefix}_item")
        entrega = st.text_input("Entrega", value=data.get("entrega", ""), key=f"{prefix}_entrega")
        situacao = st.selectbox(
            "Situação",
            options=STATUS_LIST,
            index=STATUS_LIST.index(data.get("situacao")) if data.get("situacao") in STATUS_LIST else 0,
            key=f"{prefix}_situacao",
        )
        valor = st.text_input("Valor", value=to_str(data.get("valor")), key=f"{prefix}_valor")
        valor_desconto = st.text_input("Valor Desconto", value=to_str(data.get("valor_desconto")), key=f"{prefix}_valor_desconto")
        nf = st.text_input("NF", value=data.get("nf", ""), key=f"{prefix}_nf")
        observacao = st.text_area("Observação", value=data.get("observacao", ""), key=f"{prefix}_observacao")

    if projeto_escolhido == "+ Novo projeto":
        projeto_final = projeto_novo.strip().upper()
    elif projeto_escolhido == "(Sem projeto)":
        projeto_final = ""
    else:
        projeto_final = projeto_escolhido.strip().upper()

    empresa_final = empresa_nova.strip().upper() if empresa_sel == "+ Nova empresa" else empresa_sel.strip().upper()
    setor_final = setor_novo.strip().upper() if setor_sel == "+ Novo setor" else setor_sel.strip().upper()

    return {
        "empresa": empresa_final,
        "setor": setor_final,
        "projeto": projeto_final,
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
            "projeto": excel_io.normalize_text(row.get("projeto")),
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


def resolve_selected_req_id(selected_rows: object) -> int | None:
    if isinstance(selected_rows, pd.DataFrame):
        if selected_rows.empty:
            return None
        return int(selected_rows.iloc[0]["id"])
    if isinstance(selected_rows, list):
        if not selected_rows:
            return None
        row0 = selected_rows[0]
        if isinstance(row0, dict) and row0.get("id") is not None:
            return int(row0["id"])
        if isinstance(row0, pd.Series) and row0.get("id") is not None:
            return int(row0["id"])
        return None
    if isinstance(selected_rows, dict) and selected_rows.get("id") is not None:
        return int(selected_rows["id"])
    return None


@build_dialog_decorator("Detalhes da Requisição", width="large")
def open_requisicao_dialog(selected_req_id: int) -> None:
    req_data = crud.get_by_id(selected_req_id)
    if not req_data:
        st.warning("Requisição não encontrada.")
        return

    tab_dados, tab_aprov, tab_arquivos = st.tabs(["📝 Dados", "✅ Aprovação", "📁 Arquivos"])

    with tab_dados:
        c1, c2 = st.columns(2)
        with c1:
            resumo_df = pd.DataFrame(
                [{"Campo": DISPLAY_NAMES.get(col, col), "Valor": req_data.get(col)} for col in COLUMN_ORDER]
            )
            st.dataframe(resumo_df, use_container_width=True, hide_index=True)

        with c2:
            with st.form(f"edit_req_dialog_{selected_req_id}"):
                payload = render_requisicao_form(f"edit_{selected_req_id}", req_data)
                submitted_edit = st.form_submit_button("Salvar dados da requisição", use_container_width=True)
                if submitted_edit:
                    errors = validate_payload(payload)
                    if errors:
                        for err in errors:
                            st.error(err)
                    else:
                        crud.update_requisicao(selected_req_id, payload)
                        st.session_state.open_req_dialog = False
                        st.toast("Requisição atualizada com sucesso.", icon="✅")
                        st.rerun()

            if st.button("Excluir requisição selecionada", key=f"btn_del_req_{selected_req_id}", use_container_width=True):
                crud.delete_requisicao(selected_req_id)
                st.session_state.open_req_dialog = False
                st.session_state.pop("selected_req_id", None)
                st.toast("Requisição excluída.", icon="🗑️")
                st.rerun()

        st.markdown("##### Orçamentos")
        orcs = crud.list_orcamentos(selected_req_id)
        st.dataframe(pd.DataFrame(orcs), use_container_width=True)
        with st.form(f"form_orcamento_dialog_{selected_req_id}"):
            oc1, oc2 = st.columns(2)
            fornecedor_orc = oc1.text_input("Fornecedor")
            valor_orc = oc1.text_input("Valor")
            prazo_orc = oc2.date_input("Prazo Entrega", value=None)
            cond_orc = oc2.text_input("Condições de Pagamento")
            status_orc = st.selectbox("Status orçamento", ["RECEBIDO", "APROVADO", "REJEITADO"])
            obs_orc = st.text_area("Observação orçamento")
            if st.form_submit_button("Adicionar orçamento", use_container_width=True):
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
                st.session_state.open_req_dialog = False
                st.toast("Orçamento adicionado.", icon="✅")
                st.rerun()
        if orcs:
            del_orc = st.selectbox("Excluir orçamento (ID)", [o["id"] for o in orcs], key=f"del_orc_{selected_req_id}")
            if st.button("Excluir orçamento", key=f"btn_del_orc_{selected_req_id}", use_container_width=True):
                crud.delete_orcamento(int(del_orc))
                st.session_state.open_req_dialog = False
                st.toast("Orçamento excluído.", icon="🗑️")
                st.rerun()

    with tab_aprov:
        aps = crud.list_aprovacoes(selected_req_id)
        st.dataframe(pd.DataFrame(aps), use_container_width=True)
        acao = st.selectbox("Ação", ["APROVADO", "REPROVADO", "DEVOLVIDO", "COMENTÁRIO"], key=f"acao_{selected_req_id}")
        aprovador = st.text_input("Aprovador", value="GESTOR", key=f"apr_{selected_req_id}")
        comentario = st.text_area("Comentário", key=f"obs_apr_{selected_req_id}")
        if st.button("Registrar ação", key=f"btn_apr_{selected_req_id}", use_container_width=True):
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
            st.session_state.open_req_dialog = False
            st.toast("Ação de aprovação registrada.", icon="✅")
            st.rerun()

    with tab_arquivos:
        anexos = crud.list_anexos(selected_req_id)
        st.dataframe(pd.DataFrame(anexos), use_container_width=True)
        up = st.file_uploader("Enviar anexo", key=f"anexo_{selected_req_id}")
        tipo_anexo = st.selectbox("Tipo", ["orcamento", "nf", "contrato", "outros"], key=f"tipo_{selected_req_id}")
        if st.button("Salvar anexo", key=f"btn_save_anexo_{selected_req_id}", use_container_width=True) and up is not None:
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
            st.session_state.open_req_dialog = False
            st.toast("Anexo salvo.", icon="✅")
            st.rerun()
        if anexos:
            anexo_id = st.selectbox("Baixar/Excluir anexo (ID)", [a["id"] for a in anexos], key=f"anexo_ops_{selected_req_id}")
            anexo = crud.get_anexo_conteudo(int(anexo_id))
            if anexo:
                st.download_button(
                    "Baixar anexo",
                    data=anexo["conteudo"],
                    file_name=anexo["nome_arquivo"],
                    mime=anexo.get("mime_type") or "application/octet-stream",
                    key=f"dl_{selected_req_id}_{anexo_id}",
                    use_container_width=True,
                )
            if st.button("Excluir anexo", key=f"del_anexo_{selected_req_id}", use_container_width=True):
                crud.delete_anexo(int(anexo_id))
                st.session_state.open_req_dialog = False
                st.toast("Anexo excluído.", icon="🗑️")
                st.rerun()


aba_dashboard, aba_requisicoes, aba_projetos, aba_importar = st.tabs([
    "Dashboard",
    "Requisições",
    "Projetos",
    "Importar",
])

with aba_dashboard:
    st.subheader("Métricas")
    df_metrics = metrics.fetch_dataframe(filters)

    total_gasto = metrics.total_gasto(df_metrics)
    valor_total = (df_metrics.get("valor", pd.Series(dtype=float)).fillna(0)).sum() if not df_metrics.empty else 0.0
    valor_desconto_total = (df_metrics.get("valor_desconto", pd.Series(dtype=float)).fillna(0)).sum() if not df_metrics.empty else 0.0

    pendentes_mask = df_metrics.get("situacao", pd.Series(dtype=str)).fillna("").str.upper().eq("SOLICITADO") if not df_metrics.empty else pd.Series(dtype=bool)
    pendentes_df = df_metrics[pendentes_mask] if not df_metrics.empty and not pendentes_mask.empty else pd.DataFrame()
    total_aberto = ((pendentes_df.get("valor", pd.Series(dtype=float)).fillna(0)) - (pendentes_df.get("valor_desconto", pd.Series(dtype=float)).fillna(0))).sum() if not pendentes_df.empty else 0.0
    qtd_pendentes = int(len(pendentes_df))
    saving_pct = (valor_desconto_total / valor_total * 100) if valor_total else 0.0

    with st.container():
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("💰 Total Gasto", format_currency(total_gasto))
        k2.metric("📌 Em Aberto", format_currency(float(total_aberto)))
        k3.metric("🧾 Pedidos Pendentes", str(qtd_pendentes))
        k4.metric("📉 Saving", f"{saving_pct:.2f}%")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Total por Empresa**")
        st.dataframe(metrics.total_por_empresa(df_metrics), use_container_width=True)
    with col2:
        st.markdown("**Total por Fornecedor**")
        st.dataframe(metrics.total_por_fornecedor(df_metrics), use_container_width=True)

    if st.button("Exportar Excel", key="export_dashboard", use_container_width=True):
        bytes_xlsx = excel_io.export_to_excel(df_metrics[COLUMN_ORDER])
        st.download_button(
            label="Baixar arquivo",
            data=bytes_xlsx,
            file_name=f"requisicoes_{pd.Timestamp.now():%Y%m%d_%H%M%S}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_dashboard",
            use_container_width=True,
        )

with aba_requisicoes:
    st.subheader("Requisições")

    with st.expander("➕ Criar Nova Requisição", expanded=False):
        with st.form("novo_form"):
            payload = render_requisicao_form("novo")
            submitted = st.form_submit_button("Criar requisição", use_container_width=True)
            if submitted:
                errors = validate_payload(payload)
                if errors:
                    for err in errors:
                        st.error(err)
                else:
                    crud.create_requisicao(payload)
                    st.toast("Requisição criada com sucesso.", icon="✅")
                    st.rerun()

    col_actions1, col_actions2 = st.columns([1, 1])
    with col_actions1:
        if st.button("Atualizar tabela", use_container_width=True):
            st.rerun()
    with col_actions2:
        somente_pendentes = st.checkbox("Mostrar somente pendentes (Solicitado)", value=False)

    req_filters = dict(filters)
    if somente_pendentes:
        req_filters["situacao"] = ["Solicitado"]

    total_registros = crud.count_requisicoes(req_filters)
    page_size = st.selectbox("Registros por página", [10, 20, 50], index=1)
    total_paginas = max(1, (total_registros + page_size - 1) // page_size)
    pagina = st.number_input("Página", min_value=1, max_value=total_paginas, value=1)
    offset = (pagina - 1) * page_size

    registros = crud.fetch_requisicoes(req_filters, limit=page_size, offset=offset)
    df_edit = pd.DataFrame(registros)

    if not df_edit.empty:
        editable_df = df_edit.copy()
        editable_df.insert(0, "acoes", "📝")
        for col in ["data_solicitacao", "data_compra"]:
            if col in editable_df.columns:
                editable_df[col] = pd.to_datetime(editable_df[col], errors="coerce").dt.date

        action_renderer = JsCode(
            """
            class AcaoRenderer {
                init(params) {
                    this.eGui = document.createElement('button');
                    this.eGui.innerHTML = '📝';
                    this.eGui.style.cursor = 'pointer';
                    this.eGui.style.border = 'none';
                    this.eGui.style.background = 'transparent';
                    this.eGui.style.fontSize = '16px';
                    this.eGui.addEventListener('click', () => {
                        params.api.deselectAll();
                        params.node.setSelected(true);
                    });
                }
                getGui() { return this.eGui; }
            }
            """
        )
        row_style = JsCode(
            """
            function(params) {
                const status = (params.data.situacao || '').toString().trim().toUpperCase();
                if (status === 'ENTREGUE') return {backgroundColor: '#E8F7EE'};
                if (status === 'COMPRADO') return {backgroundColor: '#FFF7D6'};
                if (status === 'SOLICITADO') return {backgroundColor: '#F5F6F7'};
                return {backgroundColor: '#F8F8F8'};
            }
            """
        )

        gb_edit = GridOptionsBuilder.from_dataframe(editable_df)
        gb_edit.configure_default_column(editable=True, filter=True, sortable=True, resizable=True)
        gb_edit.configure_column("acoes", editable=False, width=70, pinned="left", cellRenderer=action_renderer)
        gb_edit.configure_column("id", editable=False, width=80)
        gb_edit.configure_column("situacao", cellEditor="agSelectCellEditor", cellEditorParams={"values": STATUS_LIST})
        gb_edit.configure_column("projeto", width=180)
        gb_edit.configure_column("item", width=260)
        gb_edit.configure_column("observacao", width=220)
        gb_edit.configure_column("valor", type=["numericColumn"])
        gb_edit.configure_column("valor_desconto", type=["numericColumn"])
        gb_edit.configure_selection("single", use_checkbox=False)
        gb_edit.configure_grid_options(
            suppressRowClickSelection=True,
            rowSelection="single",
            rowHoverHighlight=True,
            getRowStyle=row_style,
        )

        grid_edit = AgGrid(
            editable_df,
            gridOptions=gb_edit.build(),
            update_mode=GridUpdateMode.MODEL_CHANGED | GridUpdateMode.SELECTION_CHANGED,
            fit_columns_on_grid_load=True,
            allow_unsafe_jscode=True,
            theme="streamlit",
            key="editor_requisicoes_v4",
            height=520,
        )

        if st.button("Salvar alterações da tabela", use_container_width=True):
            edited_rows = pd.DataFrame(grid_edit.get("data", []))
            changes = 0
            for _, row in edited_rows.iterrows():
                original = df_edit.loc[df_edit["id"] == row["id"]].iloc[0]
                payload = build_payload_from_row(row, original)
                if any(payload[col] != original.get(col) for col in COLUMN_ORDER):
                    crud.update_requisicao(int(row["id"]), payload)
                    changes += 1
            if changes:
                st.toast(f"{changes} requisições atualizadas.", icon="✅")
                st.rerun()
            else:
                st.info("Nenhuma alteração detectada.")

        selected_rows = grid_edit.get("selected_rows")
        selected_id = resolve_selected_req_id(selected_rows)
        if selected_id is not None:
            st.session_state.selected_req_id = selected_id

        btn_cols = st.columns([2, 1])
        with btn_cols[0]:
            if st.session_state.get("selected_req_id"):
                st.caption(f"Selecionado: ID {st.session_state['selected_req_id']}")
            else:
                st.caption("Selecione uma linha para abrir os detalhes.")
        with btn_cols[1]:
            if st.button(
                "👁️ Abrir detalhes selecionados",
                use_container_width=True,
                disabled=st.session_state.get("selected_req_id") is None,
            ):
                st.session_state.open_req_dialog = True

        if st.session_state.get("open_req_dialog") and st.session_state.get("selected_req_id") is not None:
            st.session_state.open_req_dialog = False
            if not HAS_ST_DIALOG:
                st.markdown("### Detalhes da Requisição")
            open_requisicao_dialog(int(st.session_state["selected_req_id"]))

    else:
        st.info("Nenhum registro encontrado com os filtros atuais.")

    if st.button("Exportar Excel", key="export_requisicoes", use_container_width=True):
        df_export = metrics.fetch_dataframe(req_filters)
        bytes_xlsx = excel_io.export_to_excel(df_export[COLUMN_ORDER])
        st.download_button(
            label="Baixar arquivo",
            data=bytes_xlsx,
            file_name=f"requisicoes_{pd.Timestamp.now():%Y%m%d_%H%M%S}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_requisicoes",
            use_container_width=True,
        )


with aba_projetos:
    st.subheader("Projetos")
    projetos = crud.list_projetos()
    if not projetos:
        st.info("Nenhum projeto cadastrado ainda. Ao criar uma requisição, selecione ou informe um projeto.")
    else:
        projeto_sel = st.selectbox("Selecione o projeto", options=projetos, key="projeto_sel_tab")

        reqs_projeto = crud.fetch_requisicoes_por_projeto(projeto_sel)
        orcs_projeto = crud.fetch_orcamentos_por_projeto(projeto_sel)

        c1, c2 = st.columns(2)
        with c1:
            st.metric("Requisições no projeto", len(reqs_projeto))
        with c2:
            st.metric("Orçamentos no projeto", len(orcs_projeto))

        st.markdown("#### Itens/requisições do projeto")
        st.dataframe(pd.DataFrame(reqs_projeto), use_container_width=True)

        st.markdown("#### Orçamentos consolidados do projeto")
        st.dataframe(pd.DataFrame(orcs_projeto), use_container_width=True)

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
            st.rerun()

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
