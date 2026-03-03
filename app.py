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
from src.db import get_database_url, init_db, insert_many, is_sqlite_url


st.set_page_config(page_title="Controle de Compras", layout="wide")
st.markdown(
    """
    <style>
        [data-testid="metric-container"] {
            border: 1px solid #dee2e6;
            border-radius: 10px;
            padding: 12px;
            background-color: #f8f9fa;
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_currency(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


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


# ---------------------------------------------------------------------------
# Sidebar: Filtros
# ---------------------------------------------------------------------------

def render_filters() -> dict:
    st.sidebar.header("Filtros")
    preset = st.sidebar.radio(
        "Visualização rápida",
        ["Todos", "Pendentes", "Comprados", "Entregues"],
        horizontal=False,
        key="f_preset",
    )

    if st.sidebar.button("🔄 Limpar Filtros", use_container_width=True):
        for key in [
            "f_empresa", "f_setor", "f_projeto", "f_fornecedor", "f_situacao",
            "f_data_solicitacao", "f_data_compra", "f_texto", "f_preset",
        ]:
            st.session_state.pop(key, None)
        st.rerun()

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

    with st.sidebar.expander("Filtros avançados", expanded=False):
        empresa = st.multiselect("Empresa", empresas, key="f_empresa")
        setor = st.multiselect("Setor", setores, key="f_setor")
        projeto = st.multiselect("Projeto", projetos, key="f_projeto")
        fornecedor = st.multiselect("Fornecedor", fornecedores, key="f_fornecedor")
        situacao = st.multiselect("Situação", STATUS_LIST, key="f_situacao")
        data_sol = st.date_input("Período Data Solicitação", value=(), key="f_data_solicitacao")
        data_compra = st.date_input("Período Data Compra", value=(), key="f_data_compra")
        texto = st.text_input("Busca texto", key="f_texto")

    situacoes_aplicadas = situacao or preset_map[preset]

    filters: dict = {
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


# ---------------------------------------------------------------------------
# Formulário de Requisição
# ---------------------------------------------------------------------------

def render_requisicao_form(prefix: str, data: dict | None = None) -> dict:
    data = data or {}

    projetos_existentes = crud.list_projetos()
    empresas_existentes = crud.fetch_distinct("empresa")
    setores_existentes = crud.fetch_distinct("setor")

    projeto_padrao = str(data.get("projeto") or "").strip().upper()
    empresa_padrao = str(data.get("empresa") or "").strip().upper()
    setor_padrao = str(data.get("setor") or "").strip().upper()

    # Opções dos selects
    empresa_opcoes = empresas_existentes + ["+ Nova empresa"] if empresas_existentes else ["+ Nova empresa"]
    setor_opcoes = setores_existentes + ["+ Novo setor"] if setores_existentes else ["+ Novo setor"]
    projeto_opcoes = ["(Sem projeto)"] + projetos_existentes + ["+ Novo projeto"]

    default_empresa = empresa_padrao if empresa_padrao in empresas_existentes else "+ Nova empresa"
    default_setor = setor_padrao if setor_padrao in setores_existentes else "+ Novo setor"
    default_projeto = (
        projeto_padrao if projeto_padrao in projetos_existentes
        else ("+ Novo projeto" if projeto_padrao else "(Sem projeto)")
    )

    # col1: Identificação | col2: Logística | col3: Item e Valores
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Identificação**")
        empresa_sel = st.selectbox(
            "Empresa*",
            options=empresa_opcoes,
            index=empresa_opcoes.index(default_empresa),
            key=f"{prefix}_empresa_sel",
        )
        if empresa_sel == "+ Nova empresa":
            empresa_final = st.text_input(
                "Nome da nova empresa",
                value=empresa_padrao if default_empresa == "+ Nova empresa" else "",
                key=f"{prefix}_empresa_nova",
            ).strip().upper()
        else:
            empresa_final = empresa_sel.strip().upper()

        setor_sel = st.selectbox(
            "Setor",
            options=setor_opcoes,
            index=setor_opcoes.index(default_setor),
            key=f"{prefix}_setor_sel",
        )
        if setor_sel == "+ Novo setor":
            setor_final = st.text_input(
                "Nome do novo setor",
                value=setor_padrao if default_setor == "+ Novo setor" else "",
                key=f"{prefix}_setor_novo",
            ).strip().upper()
        else:
            setor_final = setor_sel.strip().upper()

        projeto_sel = st.selectbox(
            "Projeto",
            options=projeto_opcoes,
            index=projeto_opcoes.index(default_projeto),
            key=f"{prefix}_projeto_sel",
            help="Selecione um projeto existente ou crie um novo.",
        )
        if projeto_sel == "+ Novo projeto":
            projeto_final = st.text_input(
                "Nome do novo projeto",
                value=projeto_padrao if default_projeto == "+ Novo projeto" else "",
                key=f"{prefix}_projeto_novo",
            ).strip().upper()
        elif projeto_sel == "(Sem projeto)":
            projeto_final = ""
        else:
            projeto_final = projeto_sel.strip().upper()

    with col2:
        st.markdown("**Logística**")
        requisicao = st.text_input("Requisição", value=data.get("requisicao", ""), key=f"{prefix}_requisicao")
        data_solicitacao = st.date_input(
            "Data Solicitação*",
            value=parse_date_input(data.get("data_solicitacao")) or date.today(),
            key=f"{prefix}_data_solicitacao",
        )
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
        st.markdown("**Item e Valores**")
        item = st.text_input("Item*", value=data.get("item", ""), key=f"{prefix}_item")
        qtde = st.number_input("Qtde", min_value=0, step=1, value=to_int(data.get("qtde")), key=f"{prefix}_qtde")
        entrega = st.text_input("Entrega", value=data.get("entrega", ""), key=f"{prefix}_entrega")
        situacao = st.selectbox(
            "Situação",
            options=STATUS_LIST,
            index=STATUS_LIST.index(data.get("situacao")) if data.get("situacao") in STATUS_LIST else 0,
            key=f"{prefix}_situacao",
        )
        valor = st.text_input("Valor", value=to_str(data.get("valor")), key=f"{prefix}_valor")
        valor_desconto = st.text_input(
            "Valor Desconto", value=to_str(data.get("valor_desconto")), key=f"{prefix}_valor_desconto"
        )
        nf = st.text_input("NF", value=data.get("nf", ""), key=f"{prefix}_nf")
        observacao = st.text_area("Observação", value=data.get("observacao", ""), key=f"{prefix}_observacao")

    return {
        "empresa": empresa_final,
        "setor": setor_final,
        "projeto": projeto_final,
        "requisicao": (requisicao or "").strip(),
        "data_solicitacao": data_solicitacao.isoformat() if isinstance(data_solicitacao, date) else None,
        "data_compra": None if sem_data_compra else data_compra.isoformat(),
        "fornecedor": (fornecedor or "").strip(),
        "qtde": qtde,
        "item": (item or "").strip(),
        "entrega": (entrega or "").strip(),
        "situacao": situacao,
        "valor": excel_io.parse_decimal(valor),
        "valor_desconto": excel_io.parse_decimal(valor_desconto),
        "nf": (nf or "").strip(),
        "observacao": (observacao or "").strip(),
    }


# ---------------------------------------------------------------------------
# Dialog de Detalhes
# ---------------------------------------------------------------------------

@st.dialog("Detalhes da Requisição", width="large")
def open_requisicao_dialog(selected_req_id: int) -> None:
    req_data = crud.get_by_id(selected_req_id)
    if not req_data:
        st.warning("Requisição não encontrada.")
        return

    st.caption(f"ID {selected_req_id} · {req_data.get('empresa', '')} · {req_data.get('item', '')}")

    tab_dados, tab_orc, tab_aprov, tab_arquivos = st.tabs(
        ["📝 Editar Dados", "💰 Orçamentos", "✅ Aprovações", "📁 Anexos"]
    )

    with tab_dados:
        payload = render_requisicao_form(f"edit_{selected_req_id}", req_data)
        if st.button(
            "💾 Salvar dados da requisição",
            key=f"save_edit_{selected_req_id}",
            use_container_width=True,
            type="primary",
        ):
            errors = validate_payload(payload)
            if errors:
                for err in errors:
                    st.error(err)
            else:
                crud.update_requisicao(selected_req_id, payload)
                st.session_state.pop("selected_req_id", None)
                st.toast("Requisição atualizada com sucesso.", icon="✅")
                st.rerun()

        st.markdown("---")
        if st.button(
            "🗑️ Excluir esta requisição",
            key=f"btn_del_req_{selected_req_id}",
            use_container_width=True,
            type="secondary",
        ):
            crud.delete_requisicao(selected_req_id)
            st.session_state.pop("selected_req_id", None)
            st.toast("Requisição excluída.", icon="🗑️")
            st.rerun()

    with tab_orc:
        orcs = crud.list_orcamentos(selected_req_id)
        if orcs:
            st.dataframe(pd.DataFrame(orcs), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum orçamento cadastrado para esta requisição.")

        st.markdown("##### Adicionar Orçamento")
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
                st.toast("Orçamento adicionado.", icon="✅")
                st.rerun()

        if orcs:
            st.markdown("##### Excluir Orçamento")
            del_orc = st.selectbox(
                "Selecione o orçamento pelo ID",
                [o["id"] for o in orcs],
                key=f"del_orc_{selected_req_id}",
            )
            if st.button("Excluir orçamento selecionado", key=f"btn_del_orc_{selected_req_id}", use_container_width=True):
                crud.delete_orcamento(int(del_orc))
                st.toast("Orçamento excluído.", icon="🗑️")
                st.rerun()

    with tab_aprov:
        aps = crud.list_aprovacoes(selected_req_id)
        if aps:
            st.dataframe(pd.DataFrame(aps), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhuma ação de aprovação registrada.")

        st.markdown("##### Registrar Ação")
        acao = st.selectbox(
            "Ação",
            ["APROVADO", "REPROVADO", "DEVOLVIDO", "COMENTÁRIO"],
            key=f"acao_{selected_req_id}",
        )
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
                updated = dict(req_data)
                updated["situacao"] = "Comprado"
                crud.update_requisicao(selected_req_id, updated)
            st.toast("Ação de aprovação registrada.", icon="✅")
            st.rerun()

    with tab_arquivos:
        anexos = crud.list_anexos(selected_req_id)
        if anexos:
            st.dataframe(pd.DataFrame(anexos), use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum anexo enviado.")

        st.markdown("##### Enviar Anexo")
        up = st.file_uploader("Selecione o arquivo", key=f"anexo_{selected_req_id}")
        tipo_anexo = st.selectbox(
            "Tipo de anexo",
            ["orcamento", "nf", "contrato", "outros"],
            key=f"tipo_{selected_req_id}",
        )
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
            st.toast("Anexo salvo.", icon="✅")
            st.rerun()

        if anexos:
            st.markdown("##### Baixar / Excluir Anexo")
            anexo_id = st.selectbox(
                "Selecione pelo ID",
                [a["id"] for a in anexos],
                key=f"anexo_ops_{selected_req_id}",
            )
            anexo = crud.get_anexo_conteudo(int(anexo_id))
            if anexo:
                st.download_button(
                    "⬇️ Baixar anexo",
                    data=anexo["conteudo"],
                    file_name=anexo["nome_arquivo"],
                    mime=anexo.get("mime_type") or "application/octet-stream",
                    key=f"dl_{selected_req_id}_{anexo_id}",
                    use_container_width=True,
                )
            if st.button("🗑️ Excluir anexo", key=f"del_anexo_{selected_req_id}", use_container_width=True):
                crud.delete_anexo(int(anexo_id))
                st.toast("Anexo excluído.", icon="🗑️")
                st.rerun()


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

st.title("Sistema de Controle de Requisições")

aba_dashboard, aba_requisicoes, aba_projetos, aba_importar = st.tabs([
    "📊 Dashboard",
    "📋 Requisições",
    "📁 Projetos",
    "📥 Importar",
])

# ---- Dashboard ----
with aba_dashboard:
    st.subheader("Métricas")
    df_metrics = metrics.fetch_dataframe(filters)

    total_gasto = metrics.total_gasto(df_metrics)
    valor_total = (
        df_metrics.get("valor", pd.Series(dtype=float)).fillna(0).sum()
        if not df_metrics.empty else 0.0
    )
    valor_desconto_total = (
        df_metrics.get("valor_desconto", pd.Series(dtype=float)).fillna(0).sum()
        if not df_metrics.empty else 0.0
    )

    pendentes_mask = (
        df_metrics.get("situacao", pd.Series(dtype=str))
        .fillna("").str.upper().eq("SOLICITADO")
        if not df_metrics.empty else pd.Series(dtype=bool)
    )
    pendentes_df = df_metrics[pendentes_mask] if not df_metrics.empty and not pendentes_mask.empty else pd.DataFrame()
    total_aberto = (
        (pendentes_df.get("valor", pd.Series(dtype=float)).fillna(0))
        - (pendentes_df.get("valor_desconto", pd.Series(dtype=float)).fillna(0))
    ).sum() if not pendentes_df.empty else 0.0
    qtd_pendentes = int(len(pendentes_df))
    saving_pct = (valor_desconto_total / valor_total * 100) if valor_total else 0.0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("💰 Total Gasto", format_currency(total_gasto))
    k2.metric("📌 Em Aberto", format_currency(float(total_aberto)))
    k3.metric("🧾 Pedidos Pendentes", str(qtd_pendentes))
    k4.metric("📉 Saving", f"{saving_pct:.2f}%")

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Total por Empresa**")
        st.dataframe(metrics.total_por_empresa(df_metrics), use_container_width=True, hide_index=True)
    with col2:
        st.markdown("**Total por Fornecedor**")
        st.dataframe(metrics.total_por_fornecedor(df_metrics), use_container_width=True, hide_index=True)

    st.markdown("---")
    if st.button("📄 Exportar Excel", key="export_dashboard", use_container_width=True):
        if not df_metrics.empty:
            export_cols = [c for c in COLUMN_ORDER if c in df_metrics.columns]
            bytes_xlsx = excel_io.export_to_excel(df_metrics[export_cols])
            st.download_button(
                label="⬇️ Baixar arquivo",
                data=bytes_xlsx,
                file_name=f"requisicoes_{pd.Timestamp.now():%Y%m%d_%H%M%S}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_dashboard",
                use_container_width=True,
            )
        else:
            st.info("Sem dados para exportar com os filtros atuais.")


# ---- Requisições ----
with aba_requisicoes:
    st.subheader("Requisições")

    with st.expander("➕ Criar Nova Requisição", expanded=False):
        with st.form("novo_form"):
            payload_novo = render_requisicao_form("novo")
            submitted = st.form_submit_button("Criar requisição", use_container_width=True)
            if submitted:
                errors = validate_payload(payload_novo)
                if errors:
                    for err in errors:
                        st.error(err)
                else:
                    crud.create_requisicao(payload_novo)
                    st.toast("Requisição criada com sucesso.", icon="✅")
                    st.rerun()

    col_actions1, col_actions2 = st.columns([1, 1])
    with col_actions1:
        if st.button("🔃 Atualizar tabela", use_container_width=True):
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
    df_view = pd.DataFrame(registros)

    if not df_view.empty:
        for col in ["data_solicitacao", "data_compra"]:
            if col in df_view.columns:
                df_view[col] = pd.to_datetime(df_view[col], errors="coerce").dt.date

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
                if (status === 'SOLICITADO') return {backgroundColor: '#FFEBEE', color: '#C62828'};
                if (status === 'COTA\u00c7\u00c3O')   return {backgroundColor: '#FFF3E0', color: '#BF360C'};
                if (status === 'APROVA\u00c7\u00c3O') return {backgroundColor: '#FFFDE7', color: '#827717'};
                if (status === 'COMPRADO')   return {backgroundColor: '#E8F5E9', color: '#2E7D32'};
                if (status === 'ENTREGUE')   return {backgroundColor: '#A5D6A7', color: '#1B5E20'};
                if (status === 'CANCELADO')  return {backgroundColor: '#EEEEEE', color: '#757575'};
                return {backgroundColor: '#FFFFFF', color: '#343a40'};
            }
            """
        )

        # Exibe apenas as colunas essenciais; o resto fica no modal
        _GRID_COLS = ["acoes", "id", "data_solicitacao", "empresa",
                      "item", "fornecedor", "valor", "situacao"]
        df_grid = df_view.copy()
        df_grid.insert(0, "acoes", "📝")
        df_grid = df_grid[[c for c in _GRID_COLS if c in df_grid.columns]]

        gb = GridOptionsBuilder.from_dataframe(df_grid)
        gb.configure_default_column(
            editable=False, filter=True, sortable=True, resizable=True,
            suppressSizeToFit=False,
        )
        gb.configure_column("acoes",            headerName=" ",
                            editable=False, width=52, pinned="left",
                            cellRenderer=action_renderer, suppressSizeToFit=True)
        gb.configure_column("id",               headerName="ID",
                            editable=False, width=65, suppressSizeToFit=True)
        gb.configure_column("data_solicitacao", headerName="Dt. Solicitação",
                            width=130, suppressSizeToFit=True)
        gb.configure_column("empresa",          headerName="Empresa",   width=150)
        gb.configure_column("item",             headerName="Item",      width=260)
        gb.configure_column("fornecedor",       headerName="Fornecedor", width=160)
        gb.configure_column("valor",            headerName="Valor (R$)",
                            type=["numericColumn"], width=115)
        gb.configure_column("situacao",         headerName="Status",
                            width=115, suppressSizeToFit=True)
        gb.configure_selection("single", use_checkbox=False)
        gb.configure_grid_options(
            suppressRowClickSelection=True,
            rowSelection="single",
            rowHoverHighlight=True,
            getRowStyle=row_style,
        )

        grid_result = AgGrid(
            df_grid,
            gridOptions=gb.build(),
            update_mode=GridUpdateMode.SELECTION_CHANGED,
            fit_columns_on_grid_load=False,
            allow_unsafe_jscode=True,
            theme="streamlit",
            key="viewer_requisicoes_v2",
            height=520,
        )

        selected_rows = grid_result.get("selected_rows")
        selected_id = resolve_selected_req_id(selected_rows)
        if selected_id is not None:
            st.session_state.selected_req_id = selected_id
            st.session_state.open_req_dialog = True

        if st.session_state.get("open_req_dialog") and st.session_state.get("selected_req_id") is not None:
            st.session_state.open_req_dialog = False
            open_requisicao_dialog(int(st.session_state["selected_req_id"]))

    else:
        st.info("Nenhum registro encontrado com os filtros atuais.")

    st.markdown("---")
    if st.button("📄 Exportar Excel", key="export_requisicoes", use_container_width=True):
        df_export = metrics.fetch_dataframe(req_filters)
        if not df_export.empty:
            export_cols = [c for c in COLUMN_ORDER if c in df_export.columns]
            bytes_xlsx = excel_io.export_to_excel(df_export[export_cols])
            st.download_button(
                label="⬇️ Baixar arquivo",
                data=bytes_xlsx,
                file_name=f"requisicoes_{pd.Timestamp.now():%Y%m%d_%H%M%S}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="download_requisicoes",
                use_container_width=True,
            )
        else:
            st.info("Sem dados para exportar com os filtros atuais.")


# ---- Projetos ----
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
        st.dataframe(pd.DataFrame(reqs_projeto), use_container_width=True, hide_index=True)

        st.markdown("#### Orçamentos consolidados do projeto")
        st.dataframe(pd.DataFrame(orcs_projeto), use_container_width=True, hide_index=True)


# ---- Importar ----
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

        st.caption(f"Arquivo atual: {st.session_state.get('import_file_name', 'upload')}")
        if st.button("Limpar arquivo carregado"):
            st.session_state.pop("import_file_bytes", None)
            st.session_state.pop("import_file_name", None)
            st.rerun()

        if st.button("📥 Importar", use_container_width=True):
            df_raw = excel_io.load_excel(io.BytesIO(file_bytes), sheet_name=sheet_name)
            total_before = len(df_raw)
            df_norm = excel_io.normalize_dataframe(df_raw)
            total_after = len(df_norm)
            registros = excel_io.dataframe_to_records(df_norm)
            quantidade = len(registros)
            if quantidade:
                insert_many(registros)
                st.success(f"{quantidade} registros importados com sucesso.")
                st.warning("Importação não remove duplicatas automaticamente.")
                if total_after < total_before:
                    st.info(
                        f"{total_before - total_after} linha(s) ignorada(s) por falta de "
                        "Empresa, Item ou Data Solicitação (campos obrigatórios)."
                    )
            else:
                st.info("Nenhum registro encontrado para importar.")
