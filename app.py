"""Streamlit app para controle de requisições de compras."""

from __future__ import annotations

import io
import logging
import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, JsCode
from st_aggrid.shared import GridUpdateMode

from src import auth, cotacao_pdf, crud, excel_io, metrics, pedido
from src.constants import COLUMN_ORDER, DISPLAY_NAMES, STATUS_LIST
from src.db import get_database_url, init_db, insert_many, is_sqlite_url


st.set_page_config(page_title="Controle de Compras", layout="wide")

# Logging: erros vão para o stderr (visível nos logs do Railway).
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("compras")


st.markdown(
    """
    <style>
        [data-testid="metric-container"] {
            border: 1px solid #dee2e6;
            border-radius: 10px;
            padding: 10px 12px;
            background-color: #f8f9fa;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.05rem !important;
            line-height: 1.3 !important;
            word-break: break-word;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.76rem !important;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.74rem !important;
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

# ── Autenticação ──────────────────────────────────────────────────────────
USER = auth.require_login()
PODE_EDITAR = auth.pode("editar")
PODE_EXCLUIR = auth.pode("excluir")
PODE_APROVAR = auth.pode("aprovar")
PODE_ADMIN = auth.pode("admin")
VE_LOGS = auth.pode("logs")
VE_FINANCEIRO = auth.pode("ver_financeiro")
PODE_IMPORTAR = auth.pode("importar")


def registrar_log(acao: str, entidade: str | None = None, eid: object = None, detalhe: str = "") -> None:
    crud.registrar_evento(USER.get("login", ""), USER.get("papel", ""), acao, entidade, eid, detalhe)


# Identificação do usuário + logout na sidebar
with st.sidebar:
    _u1, _u2 = st.columns([3, 1])
    _u1.caption(f"👤 **{USER['nome']}** · {auth.PAPEL_LABEL.get(USER['papel'], USER['papel'])}")
    if _u2.button("Sair", use_container_width=True):
        auth.logout()
        st.rerun()
    st.markdown("---")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def format_currency(value: object) -> str:
    """Formata no padrão monetário brasileiro: R$ 1.234,56 (— se vazio)."""
    if value is None or value == "":
        return "—"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return "R$ " + f"{num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def run_safe(fn, *args, sucesso: str | None = None, icone: str = "✅", **kwargs) -> bool:
    """Executa uma operação de banco tratando erros com mensagem amigável.

    Retorna True em caso de sucesso, False se houve erro.
    """
    try:
        fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - feedback amigável ao usuário
        # Mensagem amigável na tela + rastro completo (stack trace) nos logs.
        logger.exception("Erro ao executar operação %s", getattr(fn, "__name__", fn))
        st.error(f"Não foi possível concluir a operação: {exc}")
        return False
    if sucesso:
        st.toast(sucesso, icon=icone)
    return True


def parse_date_input(value: str | None) -> date | None:
    if not value:
        return None
    return pd.to_datetime(value).date()


def fmt_date(value: object | None) -> str:
    """Formata uma data (string ISO, date ou datetime) em DD/MM/AAAA. Vazio vira '—'."""
    if value in (None, ""):
        return "—"
    parsed = pd.to_datetime(value, errors="coerce")
    return "—" if pd.isna(parsed) else parsed.strftime("%d/%m/%Y")


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
    # Valores não podem ser negativos
    for campo, rotulo in (("valor", "Valor"), ("valor_desconto", "Valor Desconto")):
        v = payload.get(campo)
        if v is not None and v < 0:
            errors.append(f"{rotulo} não pode ser negativo.")
    # Data de compra não pode ser anterior à solicitação
    ds, dc = payload.get("data_solicitacao"), payload.get("data_compra")
    if ds and dc and dc < ds:
        errors.append("Data Compra não pode ser anterior à Data Solicitação.")
    # Fornecedor obrigatório ao marcar como Comprado/Concluído
    if payload.get("situacao") in ("Comprado", "Concluído") and not (payload.get("fornecedor") or "").strip():
        errors.append("Fornecedor é obrigatório quando a situação é 'Comprado' ou 'Concluído'.")
    return errors


def resolve_selected_row(selected_rows: object) -> dict | None:
    if isinstance(selected_rows, pd.DataFrame):
        if selected_rows.empty:
            return None
        return selected_rows.iloc[0].to_dict()
    if isinstance(selected_rows, list):
        if not selected_rows:
            return None
        row0 = selected_rows[0]
        if isinstance(row0, dict):
            return row0
        if isinstance(row0, pd.Series):
            return row0.to_dict()
        return None
    if isinstance(selected_rows, dict):
        return selected_rows
    return None


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

    # ── Contadores por preset ─────────────────────────────────────────────
    _abertos = ["Solicitado", "Cotação", "Aprovação"]
    _ct = crud.count_requisicoes({})
    _cp = crud.count_requisicoes({"situacao": _abertos})
    _cc = crud.count_requisicoes({"situacao": ["Comprado"]})
    _cn = crud.count_requisicoes({"situacao": ["Concluído"]})

    _preset_labels = [
        f"Todos ({_ct})",
        f"Em aberto ({_cp})",
        f"Comprados ({_cc})",
        f"Concluídos ({_cn})",
    ]
    _preset_situacoes = [[], _abertos, ["Comprado"], ["Concluído"]]

    preset_label = st.sidebar.radio(
        "Visualização rápida",
        _preset_labels,
        horizontal=False,
        key="f_preset",
    )
    preset_idx = _preset_labels.index(preset_label) if preset_label in _preset_labels else 0
    preset_situacoes = _preset_situacoes[preset_idx]

    if st.sidebar.button("🔄 Limpar Filtros", use_container_width=True):
        for key in [
            "f_empresa", "f_setor", "f_projeto", "f_fornecedor", "f_situacao",
            "f_data_solicitacao", "f_data_compra", "f_texto", "f_preset",
            "_last_dialog_req_id",
        ]:
            st.session_state.pop(key, None)
        st.rerun()

    # ── Busca global sempre visível ───────────────────────────────────────
    texto = st.sidebar.text_input(
        "🔍 Buscar item, fornecedor, req...",
        key="f_texto",
        placeholder="Digite para filtrar...",
    )

    # ── Atalhos de período ────────────────────────────────────────────────
    st.sidebar.caption("Período rápido:")
    _sc1, _sc2 = st.sidebar.columns(2)
    _today = date.today()
    if _sc1.button("Hoje", use_container_width=True):
        st.session_state["f_data_solicitacao"] = (_today, _today)
        st.rerun()
    if _sc2.button("Esta semana", use_container_width=True):
        _ini_sem = _today - timedelta(days=_today.weekday())
        st.session_state["f_data_solicitacao"] = (_ini_sem, _today)
        st.rerun()
    if _sc1.button("Este mês", use_container_width=True):
        st.session_state["f_data_solicitacao"] = (date(_today.year, _today.month, 1), _today)
        st.rerun()
    if _sc2.button("Último mês", use_container_width=True):
        _primeiro_mes = date(_today.year, _today.month, 1)
        _ultimo_mes_ant = _primeiro_mes - timedelta(days=1)
        st.session_state["f_data_solicitacao"] = (
            date(_ultimo_mes_ant.year, _ultimo_mes_ant.month, 1),
            _ultimo_mes_ant,
        )
        st.rerun()

    # ── Filtros avançados ─────────────────────────────────────────────────
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
        data_sol = st.date_input(
            "Período Data Solicitação",
            value=st.session_state.get("f_data_solicitacao", ()),
            key="f_data_solicitacao",
            format="DD/MM/YYYY",
        )
        data_compra = st.date_input("Período Data Compra", value=(), key="f_data_compra",
                                    format="DD/MM/YYYY")

    situacoes_aplicadas = situacao or preset_situacoes

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

    # ── Indicador de filtros ativos ───────────────────────────────────────
    _label_map = {
        "empresa": "Empresa", "setor": "Setor", "projeto": "Projeto",
        "fornecedor": "Fornecedor", "situacao": "Situação",
        "texto": "Busca", "data_solicitacao": "Data Sol.", "data_compra": "Data Compra",
    }
    _ativos = [_label_map.get(k, k) for k, v in filters.items() if v and v != [] and v is not None]
    if _ativos:
        st.sidebar.caption(f"🔍 {len(_ativos)} filtro(s): {', '.join(_ativos)}")

    return filters


filters = render_filters()

st.sidebar.markdown("---")
if PODE_ADMIN:
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
            format="DD/MM/YYYY",
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
            format="DD/MM/YYYY",
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
def open_requisicao_dialog(selected_req_id: int, want_tab: str = "dados") -> None:
    req_data = crud.get_by_id(selected_req_id)
    if not req_data:
        st.warning("Requisição não encontrada.")
        return

    st.caption(f"REQ-{selected_req_id:04d} · {req_data.get('empresa', '')} · {req_data.get('item', '')}")

    def _fmt_ts(v: object) -> str:
        if not v:
            return "—"
        try:
            return pd.to_datetime(v).strftime("%d/%m/%Y %H:%M")
        except Exception:
            return str(v)

    st.caption(
        f"🕘 Criada em {_fmt_ts(req_data.get('created_at'))} · "
        f"Última alteração {_fmt_ts(req_data.get('updated_at'))}"
    )

    tab_defs = [
        ("dados", "📝 Editar Dados"),
        ("itens", "📦 Itens"),
        ("orc", "💰 Orçamentos"),
        ("aprov", "✅ Aprovações"),
        ("anexos", "📁 Anexos"),
        ("pedido", "🧾 Pedido"),
    ]
    # A aba desejada vai para primeiro (st.tabs ativa a primeira); demais mantêm a ordem.
    if want_tab in dict(tab_defs):
        tab_defs.sort(key=lambda d: 0 if d[0] == want_tab else 1)
    tab_objs = st.tabs([lbl for _, lbl in tab_defs])
    tabs = {key: obj for (key, _), obj in zip(tab_defs, tab_objs)}

    with tabs["dados"]:
        payload = render_requisicao_form(f"edit_{selected_req_id}", req_data)
        if not PODE_EDITAR:
            st.info("👁️ Modo somente leitura — seu perfil não pode editar a requisição.")
        if PODE_EDITAR and st.button(
            "💾 Salvar dados da requisição",
            key=f"save_edit_{selected_req_id}",
            use_container_width=True,
            type="primary",
        ):
            errors = validate_payload(payload)
            if errors:
                for err in errors:
                    st.error(err)
            elif run_safe(
                crud.update_requisicao, selected_req_id, payload,
                sucesso="Requisição atualizada com sucesso.",
            ):
                registrar_log("EDITOU", "requisicao", selected_req_id)
                st.session_state.pop("selected_req_id", None)
                st.rerun()

        if PODE_EXCLUIR:
            st.markdown("---")
            with st.expander("🗑️ Excluir esta requisição"):
                st.warning("Esta ação remove a requisição e seus itens, orçamentos, aprovações e anexos.")
                confirma = st.checkbox(
                    "Confirmo que desejo excluir definitivamente.",
                    key=f"confirm_del_req_{selected_req_id}",
                )
                if st.button(
                    "Excluir definitivamente",
                    key=f"btn_del_req_{selected_req_id}",
                    use_container_width=True,
                    type="primary",
                    disabled=not confirma,
                ):
                    if run_safe(crud.delete_requisicao, selected_req_id,
                                sucesso="Requisição excluída.", icone="🗑️"):
                        registrar_log("EXCLUIU", "requisicao", selected_req_id)
                        st.session_state.pop("selected_req_id", None)
                        st.rerun()

    with tabs["itens"]:
        st.markdown("##### Itens da requisição")
        st.caption("Adicione, edite ou remova linhas. O total é calculado por item (qtde × valor unit.).")
        itens = crud.list_itens(selected_req_id)
        df_itens = pd.DataFrame(
            itens,
            columns=["descricao", "quantidade", "unidade", "valor_unitario", "observacao"],
        ) if itens else pd.DataFrame(
            columns=["descricao", "quantidade", "unidade", "valor_unitario", "observacao"]
        )
        edited_itens = st.data_editor(
            df_itens[["descricao", "quantidade", "unidade", "valor_unitario", "observacao"]],
            key=f"itens_editor_{selected_req_id}",
            num_rows="dynamic" if PODE_EDITAR else "fixed",
            use_container_width=True,
            hide_index=True,
            disabled=not PODE_EDITAR,
            column_config={
                "descricao": st.column_config.TextColumn("Descrição", required=True, width="large"),
                "quantidade": st.column_config.NumberColumn("Qtde", min_value=0, step=1, format="%g"),
                "unidade": st.column_config.TextColumn("Unid.", width="small"),
                "valor_unitario": st.column_config.NumberColumn("Valor unit. (R$)", min_value=0, format="%.2f"),
                "observacao": st.column_config.TextColumn("Observação"),
            },
        )
        # Total previsto
        _tot = 0.0
        try:
            _tot = (
                edited_itens["quantidade"].fillna(0).astype(float)
                * edited_itens["valor_unitario"].fillna(0).astype(float)
            ).sum()
            st.metric("Total previsto dos itens", format_currency(_tot))
        except Exception:
            # Valor não-numérico digitado na grade: mantém total 0 e segue.
            logger.debug("Falha ao calcular total previsto dos itens", exc_info=True)

        if PODE_EDITAR:
            atualizar_valor = st.checkbox(
                "Atualizar o Valor da requisição com o total dos itens",
                value=True,
                key=f"upd_valor_itens_{selected_req_id}",
                help="O Valor passa a ser a soma dos itens. Você ainda pode ajustá-lo manualmente na aba Editar Dados.",
            )
            if st.button("💾 Salvar itens", key=f"save_itens_{selected_req_id}", use_container_width=True, type="primary"):
                rows = edited_itens.to_dict("records")

                def _salvar_itens():
                    crud.replace_itens(selected_req_id, rows)
                    if atualizar_valor:
                        crud.set_valor_requisicao(selected_req_id, float(_tot or 0))

                if run_safe(_salvar_itens, sucesso="Itens salvos."):
                    registrar_log("EDITOU_ITENS", "requisicao", selected_req_id)
                    st.rerun()

    with tabs["orc"]:
        orcs = crud.list_orcamentos(selected_req_id)
        _status_icon = {"APROVADO": "✅", "APROVADO PARCIAL": "🟡", "REJEITADO": "❌"}
        if orcs:
            for o in orcs:
                _oid = int(o["id"])
                cab, cval, cprz, cst, cok, cno = st.columns([3, 2, 2, 2, 1, 1])
                _icon = _status_icon.get((o.get("status_orcamento") or "").upper(), "•")
                cab.markdown(f"{_icon} **#{_oid}** · {o.get('fornecedor') or '—'}")
                cval.markdown(format_currency(o.get("valor")))
                cprz.markdown(fmt_date(o.get("prazo_entrega")))
                cst.caption(o.get("status_orcamento") or "RECEBIDO")
                if PODE_APROVAR and cok.button("✅", key=f"ok_orc_{selected_req_id}_{_oid}", help="Aprovar este orçamento"):
                    crud.update_orcamento(_oid, {"status_orcamento": "APROVADO"})
                    crud.create_aprovacao({
                        "requisicao_id": selected_req_id, "orcamento_id": _oid,
                        "acao": "APROVADO", "comentario": "Aprovado na lista de orçamentos.",
                        "aprovador": USER["nome"],
                    })
                    if req_data:
                        _upd = dict(req_data); _upd["situacao"] = "Aprovação"
                        crud.update_requisicao(selected_req_id, _upd)
                    registrar_log("APROVOU", "orcamento", _oid, f"REQ {selected_req_id}")
                    st.toast(f"Orçamento #{_oid} aprovado.", icon="✅")
                    st.rerun()
                if PODE_APROVAR and cno.button("❌", key=f"no_orc_{selected_req_id}_{_oid}", help="Rejeitar este orçamento"):
                    crud.update_orcamento(_oid, {"status_orcamento": "REJEITADO"})
                    crud.create_aprovacao({
                        "requisicao_id": selected_req_id, "orcamento_id": _oid,
                        "acao": "REPROVADO", "comentario": "Rejeitado na lista de orçamentos.",
                        "aprovador": USER["nome"],
                    })
                    registrar_log("REPROVOU", "orcamento", _oid, f"REQ {selected_req_id}")
                    st.toast(f"Orçamento #{_oid} rejeitado.", icon="❌")
                    st.rerun()
            st.markdown("---")
        else:
            st.info("Nenhum orçamento cadastrado para esta requisição.")

        if PODE_EDITAR:
          st.markdown("##### Adicionar Orçamento")
          with st.form(f"form_orcamento_dialog_{selected_req_id}"):
            oc1, oc2 = st.columns(2)
            fornecedor_orc = oc1.text_input("Fornecedor")
            valor_orc = oc1.text_input("Valor")
            prazo_orc = oc2.date_input("Prazo Entrega", value=None, format="DD/MM/YYYY")
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
                registrar_log("ADICIONOU_ORCAMENTO", "requisicao", selected_req_id)
                st.toast("Orçamento adicionado.", icon="✅")
                st.rerun()

          if orcs:
            with st.expander("✏️ Editar Orçamento"):
                _edit_id = st.selectbox(
                    "Selecione o orçamento",
                    [o["id"] for o in orcs],
                    format_func=lambda i: next(
                        (f"#{o['id']} · {o.get('fornecedor') or 's/ fornecedor'} · {format_currency(o.get('valor'))}"
                         for o in orcs if o["id"] == i), str(i)),
                    key=f"edit_orc_sel_{selected_req_id}",
                )
                _o = next((o for o in orcs if o["id"] == _edit_id), None)
                if _o:
                    with st.form(f"form_edit_orc_{selected_req_id}_{_edit_id}"):
                        ec1, ec2 = st.columns(2)
                        e_forn = ec1.text_input("Fornecedor", value=_o.get("fornecedor") or "")
                        e_valor = ec1.text_input(
                            "Valor",
                            value="" if _o.get("valor") in (None, "") else str(_o.get("valor")),
                        )
                        try:
                            _prazo_val = date.fromisoformat(str(_o.get("prazo_entrega"))) if _o.get("prazo_entrega") else None
                        except (TypeError, ValueError):
                            _prazo_val = None
                        e_prazo = ec2.date_input("Prazo Entrega", value=_prazo_val, format="DD/MM/YYYY")
                        e_cond = ec2.text_input("Condições de Pagamento", value=_o.get("condicoes_pagamento") or "")
                        _st_opts = ["RECEBIDO", "APROVADO", "APROVADO PARCIAL", "REJEITADO"]
                        _cur = (_o.get("status_orcamento") or "RECEBIDO").upper()
                        e_status = st.selectbox(
                            "Status orçamento", _st_opts,
                            index=_st_opts.index(_cur) if _cur in _st_opts else 0,
                        )
                        e_obs = st.text_area("Observação orçamento", value=_o.get("observacao") or "")
                        if st.form_submit_button("💾 Salvar alterações", use_container_width=True, type="primary"):
                            if run_safe(
                                crud.update_orcamento, int(_edit_id),
                                {
                                    "fornecedor": excel_io.normalize_text(e_forn),
                                    "valor": excel_io.parse_decimal(e_valor),
                                    "prazo_entrega": e_prazo.isoformat() if e_prazo else None,
                                    "condicoes_pagamento": e_cond.strip(),
                                    "status_orcamento": e_status,
                                    "observacao": e_obs.strip(),
                                },
                                sucesso="Orçamento atualizado.",
                            ):
                                registrar_log("EDITOU_ORCAMENTO", "orcamento", int(_edit_id), f"REQ {selected_req_id}")
                                st.rerun()

        if orcs and PODE_EXCLUIR:
            with st.expander("🗑️ Excluir Orçamento"):
                del_orc = st.selectbox(
                    "Selecione o orçamento pelo ID",
                    [o["id"] for o in orcs],
                    key=f"del_orc_{selected_req_id}",
                )
                confirma_orc = st.checkbox(
                    "Confirmo a exclusão deste orçamento.",
                    key=f"confirm_del_orc_{selected_req_id}",
                )
                if st.button(
                    "Excluir orçamento selecionado",
                    key=f"btn_del_orc_{selected_req_id}",
                    use_container_width=True,
                    type="primary",
                    disabled=not confirma_orc,
                ):
                    if run_safe(crud.delete_orcamento, int(del_orc),
                                sucesso="Orçamento excluído.", icone="🗑️"):
                        st.rerun()

    with tabs["aprov"]:
        orcs_aprov = crud.list_orcamentos(selected_req_id)
        # Mapa id -> rótulo legível do orçamento
        orc_label = {
            o["id"]: f"Orç. #{o['id']} · {o.get('fornecedor') or 's/ fornecedor'} · {format_currency(o.get('valor'))}"
            for o in orcs_aprov
        }

        aps = crud.list_aprovacoes(selected_req_id)
        if aps:
            df_ap = pd.DataFrame(aps)
            if "orcamento_id" in df_ap.columns:
                df_ap["orçamento"] = df_ap["orcamento_id"].apply(
                    lambda x: orc_label.get(int(x), f"Orç. #{int(x)}") if pd.notna(x) else "— (geral)"
                )
            if "created_at" in df_ap.columns:
                df_ap["created_at"] = pd.to_datetime(df_ap["created_at"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M").fillna("")
            cols_show = [c for c in ["created_at", "orçamento", "acao", "comentario", "aprovador"] if c in df_ap.columns]
            st.dataframe(
                df_ap[cols_show], use_container_width=True, hide_index=True,
                column_config={"created_at": st.column_config.TextColumn("Data/Hora")},
            )
        else:
            st.info("Nenhuma ação de aprovação registrada.")

        st.markdown("##### Registrar Aprovação")
        if not PODE_APROVAR:
            st.info("👁️ Seu perfil não pode registrar aprovações.")
        else:
            if orcs_aprov:
                orc_escolhido = st.selectbox(
                    "Orçamento",
                    options=list(orc_label.keys()),
                    format_func=lambda i: orc_label[i],
                    key=f"apr_orc_{selected_req_id}",
                )
                acao = st.selectbox(
                    "Decisão",
                    ["APROVADO", "APROVADO PARCIAL", "REPROVADO", "COMENTÁRIO"],
                    key=f"acao_{selected_req_id}",
                )
                if acao == "APROVADO PARCIAL":
                    st.caption("Descreva no comentário o que foi aprovado (ex.: 'Orç. 3 itens 5 e 7; restante no Orç. 2').")
                aprovador = st.text_input("Aprovador", value=USER["nome"], key=f"apr_{selected_req_id}")
                comentario = st.text_area("Comentário / detalhamento", key=f"obs_apr_{selected_req_id}")
                if st.button("Registrar aprovação", key=f"btn_apr_{selected_req_id}", use_container_width=True, type="primary"):
                    crud.create_aprovacao(
                        {
                            "requisicao_id": selected_req_id,
                            "orcamento_id": int(orc_escolhido),
                            "acao": acao,
                            "comentario": comentario.strip(),
                            "aprovador": aprovador.strip() or "GESTOR",
                        }
                    )
                    # Atualiza o status do orçamento conforme a decisão
                    status_map = {
                        "APROVADO": "APROVADO",
                        "APROVADO PARCIAL": "APROVADO PARCIAL",
                        "REPROVADO": "REJEITADO",
                    }
                    if acao in status_map:
                        crud.update_orcamento(int(orc_escolhido), {"status_orcamento": status_map[acao]})
                    if acao in ("APROVADO", "APROVADO PARCIAL") and req_data:
                        updated = dict(req_data)
                        updated["situacao"] = "Aprovação"
                        crud.update_requisicao(selected_req_id, updated)
                    registrar_log(acao, "orcamento", int(orc_escolhido), f"REQ {selected_req_id}")
                    st.toast("Aprovação registrada.", icon="✅")
                    st.rerun()
            else:
                st.caption("Sem orçamentos cadastrados — aprove direto pelo valor abaixo, "
                           "ou cadastre orçamentos na aba 💰 Orçamentos.")

            # ── Aprovação direta (sem orçamento, só o valor) ──────────────────
            with st.expander("✅ Aprovar sem orçamento (valor direto)", expanded=not orcs_aprov):
                _val_atual = float(req_data.get("valor") or 0) if req_data else 0.0
                val_direto = st.number_input(
                    "Valor aprovado (R$)", min_value=0.0, value=_val_atual,
                    key=f"apr_val_direto_{selected_req_id}",
                    help="Ao aprovar, este valor é gravado na requisição.",
                )
                aprovador_d = st.text_input("Aprovador", value=USER["nome"], key=f"apr_d_{selected_req_id}")
                coment_d = st.text_area("Comentário (opcional)", key=f"obs_apr_d_{selected_req_id}")
                _dca, _dcb = st.columns(2)
                if _dca.button("✅ Aprovar requisição", key=f"btn_apr_direto_{selected_req_id}",
                               use_container_width=True, type="primary"):
                    def _aprovar_direto():
                        if req_data:
                            _u = dict(req_data)
                            _u["situacao"] = "Aprovação"
                            _u["valor"] = val_direto
                            crud.update_requisicao(selected_req_id, _u)
                        crud.create_aprovacao({
                            "requisicao_id": selected_req_id, "orcamento_id": None,
                            "acao": "APROVADO",
                            "comentario": coment_d.strip() or "Aprovado sem orçamento.",
                            "aprovador": aprovador_d.strip() or USER["nome"],
                        })
                    if run_safe(_aprovar_direto, sucesso="Requisição aprovada."):
                        registrar_log("APROVOU_SEM_ORCAMENTO", "requisicao", selected_req_id)
                        st.rerun()
                if _dcb.button("❌ Reprovar requisição", key=f"btn_rep_direto_{selected_req_id}",
                               use_container_width=True):
                    def _reprovar_direto():
                        crud.create_aprovacao({
                            "requisicao_id": selected_req_id, "orcamento_id": None,
                            "acao": "REPROVADO",
                            "comentario": coment_d.strip() or "Reprovado.",
                            "aprovador": aprovador_d.strip() or USER["nome"],
                        })
                    if run_safe(_reprovar_direto, sucesso="Requisição reprovada.", icone="❌"):
                        registrar_log("REPROVOU_SEM_ORCAMENTO", "requisicao", selected_req_id)
                        st.rerun()

    with tabs["anexos"]:
        anexos = crud.list_anexos(selected_req_id)
        orcs_anx = crud.list_orcamentos(selected_req_id)
        orc_anx_label = {o["id"]: f"Orç. #{o['id']} · {o.get('fornecedor') or 's/ fornecedor'}" for o in orcs_anx}
        if anexos:
            df_anx = pd.DataFrame(anexos)
            if "orcamento_id" in df_anx.columns:
                df_anx["orçamento"] = df_anx["orcamento_id"].apply(
                    lambda x: orc_anx_label.get(int(x), f"Orç. #{int(x)}") if pd.notna(x) else "—"
                )
            if "uploaded_at" in df_anx.columns:
                df_anx["uploaded_at"] = pd.to_datetime(df_anx["uploaded_at"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M").fillna("")
            cols_anx = [c for c in ["id", "tipo", "nome_arquivo", "orçamento", "uploaded_at"] if c in df_anx.columns]
            st.dataframe(
                df_anx[cols_anx], use_container_width=True, hide_index=True,
                column_config={"uploaded_at": st.column_config.TextColumn("Enviado em")},
            )
        else:
            st.info("Nenhum anexo enviado.")

        if PODE_EDITAR:
          st.markdown("##### Enviar Anexo")
          up = st.file_uploader("Selecione o arquivo", key=f"anexo_{selected_req_id}")
          ac1, ac2 = st.columns(2)
          tipo_anexo = ac1.selectbox(
            "Tipo de anexo",
            ["orcamento", "nf", "contrato", "outros"],
            key=f"tipo_{selected_req_id}",
          )
          # Vínculo opcional a um orçamento
          _orc_opts = [None] + [o["id"] for o in orcs_anx]
          orc_vinculo = ac2.selectbox(
            "Vincular a um orçamento (opcional)",
            options=_orc_opts,
            format_func=lambda i: "— Nenhum" if i is None else orc_anx_label.get(i, f"Orç. #{i}"),
            key=f"anexo_orc_{selected_req_id}",
          )
          if st.button("Salvar anexo", key=f"btn_save_anexo_{selected_req_id}", use_container_width=True):
            if up is None:
                st.warning("Selecione um arquivo antes de salvar.")
            elif run_safe(
                crud.create_anexo,
                {
                    "requisicao_id": selected_req_id,
                    "orcamento_id": int(orc_vinculo) if orc_vinculo else None,
                    "tipo": tipo_anexo,
                    "nome_arquivo": up.name,
                    "mime_type": up.type,
                    "conteudo": up.getvalue(),
                    "uploaded_by": USER["login"],
                },
                sucesso="Anexo salvo.",
            ):
                registrar_log("ANEXOU", "requisicao", selected_req_id, up.name)
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
            if PODE_EXCLUIR:
                confirma_anx = st.checkbox(
                    "Confirmo a exclusão deste anexo.",
                    key=f"confirm_del_anexo_{selected_req_id}",
                )
                if st.button(
                    "🗑️ Excluir anexo",
                    key=f"del_anexo_{selected_req_id}",
                    use_container_width=True,
                    disabled=not confirma_anx,
                ):
                    if run_safe(crud.delete_anexo, int(anexo_id),
                                sucesso="Anexo excluído.", icone="🗑️"):
                        registrar_log("EXCLUIU_ANEXO", "requisicao", selected_req_id)
                        st.rerun()

    with tabs["pedido"]:
        st.markdown("##### Gerar Pedido de Compra (PDF)")
        empresa_emissora = st.selectbox(
            "Empresa emissora",
            options=list(pedido.EMPRESAS.keys()),
            format_func=lambda k: pedido.EMPRESAS[k]["razao_social"],
            key=f"ped_emp_{selected_req_id}",
        )
        pc1, pc2 = st.columns(2)
        ped_numero = pc1.text_input("Número do pedido", value=f"REQ-{selected_req_id:04d}",
                                    key=f"ped_num_{selected_req_id}")
        ped_data = pc2.date_input("Data", value=date.today(), key=f"ped_data_{selected_req_id}",
                                  format="DD/MM/YYYY")

        st.markdown("**Destinatário (fornecedor)**")
        dc1, dc2 = st.columns(2)
        d_empresa = dc1.text_input("Fornecedor", value=req_data.get("fornecedor") or "",
                                   key=f"ped_forn_{selected_req_id}")
        d_ac = dc2.text_input("A/C (vendedor)", key=f"ped_ac_{selected_req_id}")
        d_cnpj = dc1.text_input("CNPJ", key=f"ped_cnpj_{selected_req_id}")
        d_email = dc2.text_input("E-mail", key=f"ped_email_{selected_req_id}")
        d_end = dc1.text_input("Endereço", key=f"ped_end_{selected_req_id}")
        d_cidade = dc2.text_input("Cidade", key=f"ped_cid_{selected_req_id}")
        d_cep = dc1.text_input("CEP", key=f"ped_cep_{selected_req_id}")

        _modo_ped = st.radio(
            "Tipo de pedido",
            ["Por itens (tabela)", "Serviço / valor fechado"],
            horizontal=True,
            key=f"ped_modo_{selected_req_id}",
            help="Use 'Serviço / valor fechado' para serviços, locação, frete ou mão de obra, "
                 "onde não faz sentido detalhar por item.",
        )
        _is_servico = _modo_ped.startswith("Serviço")

        edited_ped = None
        ped_desc_serv = ""
        ped_valor_serv = 0.0
        if _is_servico:
            ped_desc_serv = st.text_area(
                "Descrição do serviço / escopo",
                value=req_data.get("item") or "",
                height=160,
                key=f"ped_desc_serv_{selected_req_id}",
            )
            ped_valor_serv = st.number_input(
                "Valor do serviço (R$)", min_value=0.0,
                value=float(req_data.get("valor") or 0),
                key=f"ped_valor_serv_{selected_req_id}",
            )
        else:
            st.markdown("**Itens do pedido**")
            _itens_ped = crud.list_itens(selected_req_id)
            if _itens_ped:
                _df_ped = pd.DataFrame([
                    {"quant": i.get("quantidade"), "descricao": i.get("descricao"),
                     "valor_unit": i.get("valor_unitario"), "prazo": ""}
                    for i in _itens_ped
                ])
            else:
                _df_ped = pd.DataFrame([
                    {"quant": req_data.get("qtde") or 1, "descricao": req_data.get("item") or "",
                     "valor_unit": req_data.get("valor"), "prazo": req_data.get("entrega") or ""}
                ])
            edited_ped = st.data_editor(
                _df_ped, key=f"ped_itens_{selected_req_id}", num_rows="dynamic",
                use_container_width=True, hide_index=True,
                column_config={
                    "quant": st.column_config.NumberColumn("Quant.", min_value=0, format="%g"),
                    "descricao": st.column_config.TextColumn("Item / Descrição", width="large"),
                    "valor_unit": st.column_config.NumberColumn("Valor Unit. (R$)", min_value=0, format="%.2f"),
                    "prazo": st.column_config.TextColumn("Prazo de entrega"),
                },
            )

        # Condições: tenta pré-preencher pelo orçamento aprovado, se houver
        _orcs_ped = crud.list_orcamentos(selected_req_id)
        _orc_aprov = next((o for o in _orcs_ped if (o.get("status_orcamento") or "").upper().startswith("APROVADO")), None)
        pcc1, pcc2 = st.columns(2)
        ped_desc = pcc1.number_input("Desconto (R$)", min_value=0.0,
                                     value=float(req_data.get("valor_desconto") or 0),
                                     key=f"ped_desc_{selected_req_id}")
        ped_pgto = pcc2.text_input("Condições de pagamento",
                                   value=(_orc_aprov or {}).get("condicoes_pagamento") or "28 DDL",
                                   key=f"ped_pgto_{selected_req_id}")
        ped_entrega = st.text_input("Entrega", value=req_data.get("entrega") or "Alinhar com o setor solicitante",
                                    key=f"ped_entrega_{selected_req_id}")
        ped_obs = st.text_area("Observações", key=f"ped_obs_{selected_req_id}")

        if st.button("🧾 Gerar PDF do pedido", key=f"ped_gerar_{selected_req_id}",
                     use_container_width=True, type="primary"):
            dados_ped = {
                "numero": ped_numero,
                "data": ped_data.strftime("%d/%m/%Y") if isinstance(ped_data, date) else str(ped_data),
                "destinatario": {
                    "empresa": d_empresa, "ac": d_ac, "email": d_email, "cnpj": d_cnpj,
                    "endereco": d_end, "cidade": d_cidade, "cep": d_cep,
                },
                "tipo": "servico" if _is_servico else "itens",
                "itens": [] if _is_servico else edited_ped.to_dict("records"),
                "descricao_servico": ped_desc_serv if _is_servico else "",
                "valor_servico": ped_valor_serv if _is_servico else 0.0,
                "desconto": ped_desc,
                "condicoes_pagamento": ped_pgto,
                "entrega": ped_entrega,
                "observacoes": ped_obs,
            }
            try:
                st.session_state[f"_pdf_{selected_req_id}"] = pedido.gerar_pedido_pdf(empresa_emissora, dados_ped)
                st.session_state[f"_pdf_nome_{selected_req_id}"] = f"Pedido_{ped_numero}.pdf"
                registrar_log("GEROU_PEDIDO", "requisicao", selected_req_id, f"{empresa_emissora} · {ped_numero}")
                # Só agora (pedido emitido) a requisição vira "Comprado".
                if req_data and req_data.get("situacao") not in ("Comprado", "Concluído", "Cancelado"):
                    _upd = dict(req_data)
                    _upd["situacao"] = "Comprado"
                    if not (_upd.get("data_compra") or ""):
                        _upd["data_compra"] = date.today().isoformat()
                    if not (_upd.get("fornecedor") or "").strip() and _orc_aprov:
                        _upd["fornecedor"] = _orc_aprov.get("fornecedor") or _upd.get("fornecedor")
                    crud.update_requisicao(selected_req_id, _upd)
                    registrar_log("MARCOU_COMPRADO", "requisicao", selected_req_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Erro ao gerar PDF do pedido (req=%s)", selected_req_id)
                st.error(f"Erro ao gerar o PDF: {exc}")

        _pdf_bytes = st.session_state.get(f"_pdf_{selected_req_id}")
        if _pdf_bytes:
            st.success("Pedido gerado! Baixe abaixo.")
            st.download_button(
                "⬇️ Baixar pedido (PDF)",
                data=_pdf_bytes,
                file_name=st.session_state.get(f"_pdf_nome_{selected_req_id}", "pedido.pdf"),
                mime="application/pdf",
                key=f"ped_dl_{selected_req_id}",
                use_container_width=True,
            )

        st.markdown("---")
        _sit_atual = (req_data or {}).get("situacao") or "—"
        st.caption(f"Situação atual da requisição: **{_sit_atual}**")
        if PODE_EDITAR and _sit_atual not in ("Comprado", "Concluído", "Cancelado"):
            st.caption("Use abaixo para marcar como comprada manualmente, sem precisar gerar o pedido.")
            if st.button("✅ Marcar como Comprado (manual)", key=f"mark_comprado_{selected_req_id}", use_container_width=True):
                _upd = dict(req_data)
                _upd["situacao"] = "Comprado"
                if not (_upd.get("data_compra") or ""):
                    _upd["data_compra"] = date.today().isoformat()
                if run_safe(crud.update_requisicao, selected_req_id, _upd,
                            sucesso="Requisição marcada como Comprado."):
                    registrar_log("MARCOU_COMPRADO_MANUAL", "requisicao", selected_req_id)
                    st.rerun()


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

st.title("Sistema de Controle de Requisições")

_badge_count = crud.count_requisicoes(filters)

_tab_specs: list[tuple[str, str]] = []
if VE_FINANCEIRO:
    _tab_specs.append(("dashboard", "📊 Dashboard"))
_tab_specs.append(("requisicoes", f"📋 Requisições ({_badge_count})"))
if VE_FINANCEIRO:
    _tab_specs.append(("analises", "📈 Análises"))
    _tab_specs.append(("projetos", "📁 Projetos"))
if PODE_IMPORTAR:
    _tab_specs.append(("importar", "📥 Importar"))
if VE_LOGS:
    _tab_specs.append(("atividades", "🗒️ Atividades"))
if PODE_ADMIN:
    _tab_specs.append(("admin", "⚙️ Admin"))
_tab_objs = st.tabs([_lbl for _, _lbl in _tab_specs])
TABS = {_k: _o for (_k, _), _o in zip(_tab_specs, _tab_objs)}

# ---- Dashboard ----
if "dashboard" in TABS:
  with TABS["dashboard"]:
    import plotly.express as px

    st.subheader("Visão Geral")
    df_metrics = metrics.fetch_dataframe(filters)

    # Cálculos principais
    _valor_total = float(df_metrics["valor"].fillna(0).sum()) if not df_metrics.empty else 0.0
    _desconto_total = float(df_metrics["valor_desconto"].fillna(0).sum()) if not df_metrics.empty else 0.0
    _total_reqs = len(df_metrics)
    _em_aberto = metrics.valor_em_aberto(df_metrics)
    _ticket = metrics.ticket_medio(df_metrics)
    _tempo_med = metrics.tempo_medio_atendimento(df_metrics)
    _saving_pct = (_desconto_total / _valor_total * 100) if _valor_total else 0.0

    # --- Bloco 1: KPIs principais ---
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("📦 Total de Requisições", str(_total_reqs))
    k2.metric("💰 Valor Total", format_currency(_valor_total))
    k3.metric("💼 Em Aberto", format_currency(_em_aberto))
    k4.metric("🎯 Ticket Médio", format_currency(_ticket))
    k5.metric(
        "⏱️ Tempo Médio",
        f"{_tempo_med:.1f} dias" if _tempo_med else "—",
    )
    k6.metric(
        "📉 Saving",
        f"{_saving_pct:.2f}%" if _saving_pct else "—",
    )

    st.markdown("---")

    # --- Bloco 2: Breakdown por status ---
    st.markdown("**Situação das Requisições**")
    df_sit = metrics.contagem_por_situacao(df_metrics)
    if not df_sit.empty:
        _status_cols = st.columns(len(df_sit))
        for i, row in df_sit.iterrows():
            _status_cols[i % len(_status_cols)].metric(
                label=str(row["situacao"] or "Sem status"),
                value=str(int(row["quantidade"])),
                delta=format_currency(float(row["valor_total"])),
                delta_color="off",
            )
    else:
        st.info("Sem dados de situação.")

    st.markdown("---")

    # --- Bloco 3: Gráficos ---
    gc1, gc2 = st.columns(2)
    with gc1:
        st.markdown("**Valor por Status**")
        if not df_sit.empty:
            fig_sit = px.bar(
                df_sit.sort_values("valor_total"),
                x="valor_total",
                y="situacao",
                orientation="h",
                labels={"valor_total": "Valor (R$)", "situacao": ""},
                color="situacao",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_sit.update_layout(
                showlegend=False,
                margin=dict(l=0, r=0, t=10, b=0),
                height=300,
            )
            st.plotly_chart(fig_sit, use_container_width=True)
        else:
            st.info("Sem dados.")

    with gc2:
        st.markdown("**Top 10 Fornecedores por Valor**")
        df_top_forn = metrics.top_fornecedores(df_metrics, n=10)
        if not df_top_forn.empty:
            fig_forn = px.bar(
                df_top_forn.sort_values("valor_total"),
                x="valor_total",
                y="fornecedor",
                orientation="h",
                labels={"valor_total": "Valor (R$)", "fornecedor": ""},
                color_discrete_sequence=["#4C72B0"],
            )
            fig_forn.update_layout(
                showlegend=False,
                margin=dict(l=0, r=0, t=10, b=0),
                height=300,
            )
            st.plotly_chart(fig_forn, use_container_width=True)
        else:
            st.info("Sem dados.")

    st.markdown("---")

    # --- Bloco 4: Tabelas resumo ---
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Total por Empresa**")
        df_emp = metrics.total_por_empresa(df_metrics)
        if not df_emp.empty:
            df_emp = df_emp.sort_values("total", ascending=False)
            df_emp.columns = ["Empresa", "Total (R$)"]
            df_emp["Total (R$)"] = df_emp["Total (R$)"].apply(format_currency)
        st.dataframe(df_emp, use_container_width=True, hide_index=True)
    with col2:
        st.markdown("**Total por Fornecedor**")
        df_forn_tab = metrics.total_por_fornecedor(df_metrics)
        if not df_forn_tab.empty:
            df_forn_tab = df_forn_tab.sort_values("total", ascending=False)
            df_forn_tab.columns = ["Fornecedor", "Total (R$)"]
            df_forn_tab["Total (R$)"] = df_forn_tab["Total (R$)"].apply(format_currency)
        st.dataframe(df_forn_tab, use_container_width=True, hide_index=True)

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
if "requisicoes" in TABS:
  with TABS["requisicoes"]:
    st.subheader("Requisições")

    if PODE_EDITAR:
      with st.expander("➕ Criar Nova Requisição", expanded=False):
        payload_novo = render_requisicao_form("novo")

        st.markdown("##### Itens (opcional)")
        st.caption("Detalhe vários itens aqui. Se preencher, o Valor pode ser calculado pela soma.")
        _df_novo_itens = pd.DataFrame(
            columns=["descricao", "quantidade", "unidade", "valor_unitario", "observacao"]
        )
        _novo_itens = st.data_editor(
            _df_novo_itens,
            key="novo_itens_editor",
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            column_config={
                "descricao": st.column_config.TextColumn("Descrição", width="large"),
                "quantidade": st.column_config.NumberColumn("Qtde", min_value=0, step=1, format="%g"),
                "unidade": st.column_config.TextColumn("Unid.", width="small"),
                "valor_unitario": st.column_config.NumberColumn("Valor unit. (R$)", min_value=0, format="%.2f"),
                "observacao": st.column_config.TextColumn("Observação"),
            },
        )
        _tot_novo = 0.0
        try:
            _tot_novo = float((
                _novo_itens["quantidade"].fillna(0).astype(float)
                * _novo_itens["valor_unitario"].fillna(0).astype(float)
            ).sum())
        except Exception:
            logger.debug("Falha ao calcular total dos itens na criação", exc_info=True)
        _tem_itens = not _novo_itens.dropna(how="all").empty
        _usar_total = False
        if _tem_itens:
            st.metric("Total dos itens", format_currency(_tot_novo))
            _usar_total = st.checkbox(
                "Usar a soma dos itens como Valor da requisição",
                value=True, key="novo_usar_total_itens",
            )

        if st.button("Criar requisição", key="btn_criar_req", use_container_width=True, type="primary"):
            if _tem_itens and _usar_total:
                payload_novo["valor"] = _tot_novo
            errors = validate_payload(payload_novo)
            if errors:
                for err in errors:
                    st.error(err)
            else:
                _novo_id = crud.create_requisicao(payload_novo)
                if _novo_id and _tem_itens:
                    _rows = _novo_itens.dropna(how="all").to_dict("records")
                    crud.replace_itens(int(_novo_id), _rows)
                registrar_log("CRIOU", "requisicao", _novo_id, payload_novo.get("item", ""))
                st.toast("Requisição criada com sucesso.", icon="✅")
                st.rerun()

      with st.expander("📄 Importar PDF (Cotação ou Pedido de Compra)", expanded=False):
        st.caption("Envie um ou mais PDFs. Cartas de Cotação viram requisições 'Solicitado'; "
                   "Pedidos de Compra viram 'Comprado' (com fornecedor e valores). Cada PDF vira uma requisição.")
        _pdfs = st.file_uploader(
            "Arquivos PDF", type=["pdf"], accept_multiple_files=True, key="cotacao_pdf_uploader",
        )
        if _pdfs:
            _parsed: list[dict] = []
            for _f in _pdfs:
                try:
                    _d = cotacao_pdf.parse_documento(_f.getvalue())
                    _d["_arquivo"] = _f.name
                    _parsed.append(_d)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Erro ao ler PDF de cotação: %s", _f.name)
                    st.error(f"❌ {_f.name}: não consegui ler ({exc}).")

            for _d in _parsed:
                _tipo_lbl = "🧾 Pedido de Compra" if _d.get("tipo") == "pedido" else "📋 Carta de Cotação"
                st.markdown(f"**{_tipo_lbl} Nº {_d.get('requisicao') or '?'}** · _{_d['_arquivo']}_ "
                            f"→ situação **{_d.get('situacao')}**")
                _c1, _c2, _c3, _c4 = st.columns(4)
                _c1.caption(f"Empresa: **{_d.get('empresa') or '—'}**")
                _c2.caption(f"Dt. Solicitação: **{fmt_date(_d.get('data_solicitacao'))}**")
                _c3.caption(f"Sug./Prev. Entrega: **{_d.get('entrega') or '—'}**")
                _c4.caption(f"Itens: **{len(_d.get('itens') or [])}**")
                if _d.get("tipo") == "pedido":
                    _p1, _p2, _p3 = st.columns(3)
                    _p1.caption(f"Fornecedor: **{_d.get('fornecedor') or '—'}**")
                    _p2.caption(f"Valor: **{format_currency(_d.get('valor'))}**")
                    _p3.caption(f"Obs.: {_d.get('observacao') or '—'}")
                if _d.get("itens"):
                    _cols_prev = ["codigo", "descricao", "quantidade", "unidade"]
                    if _d.get("tipo") == "pedido":
                        _cols_prev += ["valor_unitario", "valor_total"]
                    st.dataframe(
                        pd.DataFrame(_d["itens"])[_cols_prev],
                        use_container_width=True, hide_index=True,
                    )
                for _e in _d.get("erros") or []:
                    st.warning(_e)

            if _parsed and st.button("✅ Importar requisições", key="btn_import_cotacao",
                                     use_container_width=True, type="primary"):
                _ok, _falhas = 0, 0
                for _d in _parsed:
                    _payload = {
                        "requisicao": _d.get("requisicao"),
                        "empresa": (_d.get("empresa") or "").upper(),
                        "item": _d.get("item"),
                        "fornecedor": _d.get("fornecedor") or None,
                        "data_solicitacao": _d.get("data_solicitacao"),
                        "data_compra": _d.get("data_compra"),
                        "entrega": _d.get("entrega"),
                        "situacao": _d.get("situacao") or "Solicitado",
                        "valor": _d.get("valor"),
                        "valor_desconto": _d.get("valor_desconto"),
                        "observacao": _d.get("observacao") or None,
                    }
                    _errs = validate_payload(_payload)
                    if _errs:
                        _falhas += 1
                        st.error(f"❌ {_d['_arquivo']}: {' / '.join(_errs)}")
                        continue

                    def _criar(_p=_payload, _itens=_d.get("itens") or []):
                        _nid = crud.create_requisicao(_p)
                        if _nid and _itens:
                            _rows = [{
                                "descricao": it.get("descricao"),
                                "quantidade": it.get("quantidade"),
                                "unidade": it.get("unidade"),
                                "valor_unitario": it.get("valor_unitario"),
                                "observacao": (f"Cód: {it.get('codigo')}" if it.get("codigo") else ""),
                            } for it in _itens]
                            crud.replace_itens(int(_nid), _rows)
                        return _nid

                    if run_safe(_criar):
                        _ok += 1
                        registrar_log("IMPORTOU_PDF", "requisicao",
                                      detalhe=f"{_d.get('tipo')} {_d.get('requisicao')} · {len(_d.get('itens') or [])} itens")
                    else:
                        _falhas += 1
                if _ok:
                    st.success(f"{_ok} requisição(ões) importada(s)."
                               + (f" {_falhas} com erro." if _falhas else ""))
                    st.rerun()

    req_filters = dict(filters)
    total_registros = crud.count_requisicoes(req_filters)

    # Controles enxutos: contador + atualizar. Ordenação fixa (mais recentes primeiro).
    _info, _btn = st.columns([4, 1])
    _info.caption(f"{total_registros} requisição(ões) · use a sidebar para filtrar")
    if _btn.button("🔃 Atualizar", use_container_width=True):
        st.rerun()

    page_size = 20
    total_paginas = max(1, (total_registros + page_size - 1) // page_size)
    pagina = (
        st.number_input("Página", min_value=1, max_value=total_paginas, value=1)
        if total_paginas > 1 else 1
    )
    offset = (pagina - 1) * page_size

    registros = crud.fetch_requisicoes(
        req_filters, limit=page_size, offset=offset,
        order_by="data_solicitacao",
        descending=True,
    )
    df_view = pd.DataFrame(registros)

    if not df_view.empty:
        # Mantém as datas em ISO (YYYY-MM-DD) para ordenar/filtrar corretamente;
        # a exibição em DD/MM/YYYY é feita por valueFormatter no grid.
        for col in ["data_solicitacao", "data_compra"]:
            if col in df_view.columns:
                df_view[col] = (
                    pd.to_datetime(df_view[col], errors="coerce")
                    .dt.strftime("%Y-%m-%d")
                    .fillna("")
                )

        date_formatter = JsCode(
            """
            function(params) {
                if (!params.value) return '';
                var p = String(params.value).split('-');
                if (p.length !== 3) return params.value;
                return p[2] + '/' + p[1] + '/' + p[0];
            }
            """
        )

        req_renderer = JsCode(
            """
            class ReqRenderer {
                init(params) {
                    this.eGui = document.createElement('a');
                    this.eGui.innerHTML = params.value || '';
                    this.eGui.title = 'Abrir detalhes, itens, orçamentos, aprovações e anexos';
                    this.eGui.style.cursor = 'pointer';
                    this.eGui.style.color = '#4C72B0';
                    this.eGui.style.fontWeight = '600';
                    this.eGui.style.textDecoration = 'underline';
                    this.eGui.addEventListener('click', () => {
                        params.node.setDataValue('_want_tab', 'dados');
                        params.api.deselectAll();
                        params.node.setSelected(true);
                    });
                }
                getGui() { return this.eGui; }
            }
            """
        )

        def _badge_renderer(want_tab: str) -> JsCode:
            return JsCode(
                """
                class BadgeRenderer {
                    init(params) {
                        this.eGui = document.createElement('span');
                        this.eGui.innerHTML = params.value || '';
                        this.eGui.title = 'Abrir nesta aba';
                        this.eGui.style.cursor = 'pointer';
                        this.eGui.style.textDecoration = 'underline dotted';
                        this.eGui.addEventListener('click', () => {
                            params.node.setDataValue('_want_tab', '__WANT__');
                            params.api.deselectAll();
                            params.node.setSelected(true);
                        });
                    }
                    getGui() { return this.eGui; }
                }
                """.replace("__WANT__", want_tab)
            )

        orc_renderer = _badge_renderer("orc")
        anx_renderer = _badge_renderer("anexos")

        currency_formatter = JsCode(
            """
            function(params) {
                if (params.value === null || params.value === undefined || params.value === '') return '';
                return 'R$ ' + Number(params.value).toLocaleString('pt-BR',
                    {minimumFractionDigits: 2, maximumFractionDigits: 2});
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
                if (status === 'CONCLU\u00cdDO') return {backgroundColor: '#A5D6A7', color: '#1B5E20'};
                if (status === 'CANCELADO')  return {backgroundColor: '#EEEEEE', color: '#757575'};
                return {backgroundColor: '#FFFFFF', color: '#343a40'};
            }
            """
        )

        # Contagem de orçamentos/anexos por requisição
        _ids = [int(i) for i in df_view["id"].tolist()]
        _counts = crud.fetch_counts(_ids)

        # Colunas fixas e essenciais; detalhes ficam no modal.
        _GRID_COLS = ["req", "requisicao", "data_solicitacao", "data_compra", "empresa",
                      "item", "fornecedor", "valor", "situacao", "col_orc", "col_anx"]
        df_grid = df_view.copy()
        df_grid["req"] = df_grid["id"].apply(lambda i: f"REQ-{int(i):04d}")
        df_grid["col_orc"] = df_grid["id"].apply(
            lambda i: f"💰 {_counts.get(int(i), {}).get('orcamentos', 0)}"
        )
        df_grid["col_anx"] = df_grid["id"].apply(
            lambda i: f"📎 {_counts.get(int(i), {}).get('anexos', 0)}"
        )
        # Coluna auxiliar (oculta): guarda qual aba abrir ao clicar
        df_grid["_want_tab"] = ""
        # Mantém 'id' oculto para resolver a seleção/abertura do modal
        df_grid = df_grid[[c for c in (_GRID_COLS + ["id", "_want_tab"]) if c in df_grid.columns]]

        gb = GridOptionsBuilder.from_dataframe(df_grid)
        gb.configure_default_column(
            editable=False, filter=True, sortable=True, resizable=True,
            suppressSizeToFit=False,
        )
        gb.configure_column("req",              headerName="Requisição",
                            editable=False, width=120, pinned="left", suppressSizeToFit=True,
                            cellRenderer=req_renderer, filter=False)
        gb.configure_column("id",               hide=True)
        gb.configure_column("requisicao",       headerName="Cód. Original",
                            width=130, suppressSizeToFit=True, editable=PODE_EDITAR)
        gb.configure_column("item",             headerName="Item",      width=260,
                            editable=PODE_EDITAR)
        if "data_solicitacao" in df_grid.columns:
            gb.configure_column("data_solicitacao", headerName="Dt. Solicitação",
                                width=130, suppressSizeToFit=True,
                                valueFormatter=date_formatter,
                                editable=PODE_EDITAR,
                                cellEditor="agDateStringCellEditor")
        if "data_compra" in df_grid.columns:
            gb.configure_column("data_compra",      headerName="Dt. Compra",
                                width=120, suppressSizeToFit=True,
                                valueFormatter=date_formatter,
                                editable=PODE_EDITAR,
                                cellEditor="agDateStringCellEditor")
        if "empresa" in df_grid.columns:
            gb.configure_column("empresa",          headerName="Empresa",   width=150,
                                editable=PODE_EDITAR)
        if "fornecedor" in df_grid.columns:
            gb.configure_column("fornecedor",       headerName="Fornecedor", width=160,
                                editable=PODE_EDITAR)
        if "valor" in df_grid.columns:
            gb.configure_column("valor",            headerName="Valor (R$)",
                                type=["numericColumn"], width=120,
                                valueFormatter=currency_formatter,
                                editable=PODE_EDITAR,
                                cellEditor="agNumberCellEditor")
        if "col_orc" in df_grid.columns:
            gb.configure_column("col_orc",          headerName="Orç.",
                                editable=False, width=80, suppressSizeToFit=True,
                                filter=False, sortable=False, cellRenderer=orc_renderer)
        if "col_anx" in df_grid.columns:
            gb.configure_column("col_anx",          headerName="Anexos",
                                editable=False, width=90, suppressSizeToFit=True,
                                filter=False, sortable=False, cellRenderer=anx_renderer)
        gb.configure_column("_want_tab",        hide=True)
        gb.configure_column(
            "situacao",
            headerName="Status",
            width=130,
            suppressSizeToFit=True,
            editable=PODE_EDITAR,
            cellEditor="agSelectCellEditor",
            cellEditorParams={"values": STATUS_LIST},
            singleClickEdit=True,
        )
        gb.configure_selection("single", use_checkbox=False)
        gb.configure_grid_options(
            suppressRowClickSelection=True,
            rowSelection="single",
            rowHoverHighlight=True,
            getRowStyle=row_style,
            singleClickEdit=True,
            stopEditingWhenCellsLoseFocus=True,
        )

        if PODE_EDITAR:
            st.caption(
                "✏️ Clique numa célula de **Status**, **Empresa**, **Item**, **Fornecedor** ou **Valor** "
                "para editar; ao sair da célula, salva automaticamente. "
                "Clique no **código REQ** para abrir os detalhes."
            )
        else:
            st.caption("👁️ Modo somente leitura. Clique no **código REQ** para ver os detalhes.")
        grid_result = AgGrid(
            df_grid,
            gridOptions=gb.build(),
            update_mode=GridUpdateMode.VALUE_CHANGED | GridUpdateMode.SELECTION_CHANGED,
            fit_columns_on_grid_load=True,
            allow_unsafe_jscode=True,
            theme="streamlit",
            key=f"viewer_requisicoes_v2_{st.session_state.get('_grid_nonce', 0)}",
            height=520,
        )

        # ── Detectar edição inline (Status, Fornecedor, Valor) ────────────
        df_returned = grid_result.get("data")
        if PODE_EDITAR and df_returned is not None and not df_returned.empty and "id" in df_returned.columns:
            _editaveis = ["situacao", "fornecedor", "valor", "empresa", "item",
                          "requisicao", "data_solicitacao", "data_compra"]
            for _, ret_row in df_returned.iterrows():
                _rid = ret_row.get("id")
                if _rid is None:
                    continue
                _orig_row = df_grid.loc[df_grid["id"] == _rid]
                if _orig_row.empty:
                    continue
                _updates: dict = {}
                for _col in _editaveis:
                    _new = ret_row.get(_col)
                    _old = _orig_row.iloc[0].get(_col)
                    if _col == "valor":
                        _nf = None if _new in (None, "") else float(_new)
                        _of = None if _old in (None, "") else float(_old)
                        if _nf != _of:
                            _updates["valor"] = _nf
                    elif _col == "situacao":
                        if _new and str(_old) != str(_new):
                            _updates["situacao"] = str(_new)
                    elif _col in ("empresa", "item"):
                        # Campos obrigatórios: não permite salvar vazio
                        _nv = str(_new or "").strip()
                        if _nv and _nv != str(_old or "").strip():
                            _updates[_col] = _nv.upper() if _col == "empresa" else _nv
                    elif _col == "data_solicitacao":
                        # Obrigatória: só atualiza se vier valor e for diferente
                        _nv = str(_new or "").strip()[:10]
                        if _nv and _nv != str(_old or "").strip()[:10]:
                            _updates["data_solicitacao"] = _nv
                    elif _col == "data_compra":
                        # Opcional: aceita limpar (vira nulo)
                        _nv = str(_new or "").strip()[:10]
                        if _nv != str(_old or "").strip()[:10]:
                            _updates["data_compra"] = _nv or None
                    elif _col == "requisicao":
                        if (str(_new or "").strip()) != (str(_old or "").strip()):
                            _updates["requisicao"] = str(_new or "").strip()
                    else:  # fornecedor
                        if (str(_new or "").strip()) != (str(_old or "").strip()):
                            _updates["fornecedor"] = str(_new or "").strip()
                if _updates:
                    crud.update_requisicao(int(_rid), _updates)
                    registrar_log("EDITOU_INLINE", "requisicao", int(_rid), ", ".join(_updates.keys()))
                    st.toast(f"REQ-{int(_rid):04d} atualizada.", icon="✅")
                    st.session_state.pop("_last_dialog_req_id", None)
                    st.rerun()

        # ── Detectar seleção para abrir dialog ────────────────────────────
        selected_rows = grid_result.get("selected_rows")
        selected_row = resolve_selected_row(selected_rows)
        selected_id = resolve_selected_req_id(selected_rows)
        if selected_id is None:
            # Sem seleção (ex.: após remontar a grid): libera reabrir qualquer linha
            st.session_state.pop("_last_dialog_req_id", None)
        elif selected_id != st.session_state.get("_last_dialog_req_id"):
            st.session_state.selected_req_id = selected_id
            st.session_state.open_req_dialog = True
            st.session_state["_want_tab"] = (selected_row or {}).get("_want_tab") or "dados"

        if st.session_state.get("open_req_dialog") and st.session_state.get("selected_req_id") is not None:
            st.session_state.open_req_dialog = False
            st.session_state["_last_dialog_req_id"] = st.session_state["selected_req_id"]
            # Bump no nonce → na próxima execução a grid remonta sem seleção,
            # permitindo reabrir a mesma requisição depois de fechar o modal.
            st.session_state["_grid_nonce"] = st.session_state.get("_grid_nonce", 0) + 1
            open_requisicao_dialog(
                int(st.session_state["selected_req_id"]),
                want_tab=st.session_state.get("_want_tab", "dados"),
            )

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


# ---- Análises ----
if "analises" in TABS:
  with TABS["analises"]:
    import plotly.express as px  # noqa: F811 — already imported in dashboard block

    st.subheader("Análises de Compras")

    df_an = metrics.fetch_dataframe(filters)

    if df_an.empty:
        st.info("Nenhum dado disponível com os filtros atuais.")
    else:
        # ── Seção 1: Evolução Temporal ───────────────────────────────────────
        st.markdown("### 📅 Evolução Temporal")
        an_c1, an_c2 = st.columns(2)

        with an_c1:
            st.markdown("**Requisições por Mês (data de solicitação)**")
            df_evol = metrics.evolucao_mensal(df_an, date_col="data_solicitacao")
            if not df_evol.empty:
                fig_evol = px.bar(
                    df_evol,
                    x="mes",
                    y="quantidade",
                    labels={"mes": "Mês", "quantidade": "Nº Requisições"},
                    color_discrete_sequence=["#4C72B0"],
                )
                fig_evol.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=280)
                st.plotly_chart(fig_evol, use_container_width=True)
            else:
                st.info("Sem datas de solicitação registradas.")

        with an_c2:
            st.markdown("**Valor Comprado por Mês (data de compra)**")
            _df_comprado = df_an[
                df_an["situacao"].fillna("").str.lower().isin(
                    {"comprado", "concluído", "concluido", "entregue"}
                )
            ]
            df_evol_compra = metrics.evolucao_mensal(_df_comprado, date_col="data_compra")
            if not df_evol_compra.empty:
                fig_evol_c = px.line(
                    df_evol_compra,
                    x="mes",
                    y="valor_total",
                    markers=True,
                    labels={"mes": "Mês", "valor_total": "Valor (R$)"},
                    color_discrete_sequence=["#2ca02c"],
                )
                fig_evol_c.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=280)
                st.plotly_chart(fig_evol_c, use_container_width=True)
            else:
                st.info("Sem registros de compra com data preenchida.")

        st.markdown("---")

        # ── Seção 2: Distribuição por Status ────────────────────────────────
        st.markdown("### 📊 Distribuição por Status")
        df_sit_an = metrics.contagem_por_situacao(df_an)
        an_s1, an_s2 = st.columns(2)

        with an_s1:
            st.markdown("**Quantidade de Requisições por Status**")
            if not df_sit_an.empty:
                fig_pie = px.pie(
                    df_sit_an,
                    names="situacao",
                    values="quantidade",
                    hole=0.4,
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig_pie.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
                st.plotly_chart(fig_pie, use_container_width=True)

        with an_s2:
            st.markdown("**Valor Total por Status**")
            if not df_sit_an.empty:
                fig_val_sit = px.bar(
                    df_sit_an.sort_values("valor_total", ascending=False),
                    x="situacao",
                    y="valor_total",
                    labels={"situacao": "", "valor_total": "Valor (R$)"},
                    color="situacao",
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig_val_sit.update_layout(
                    showlegend=False,
                    margin=dict(l=0, r=0, t=10, b=0),
                    height=300,
                )
                st.plotly_chart(fig_val_sit, use_container_width=True)

        st.markdown("---")

        # ── Seção 3: Análise de Fornecedores ────────────────────────────────
        st.markdown("### 🏭 Análise de Fornecedores")
        an_f1, an_f2 = st.columns(2)

        with an_f1:
            st.markdown("**Top 15 Fornecedores por Valor**")
            df_top15 = metrics.top_fornecedores(df_an, n=15)
            if not df_top15.empty:
                fig_top15 = px.bar(
                    df_top15.sort_values("valor_total"),
                    x="valor_total",
                    y="fornecedor",
                    orientation="h",
                    labels={"valor_total": "Valor (R$)", "fornecedor": ""},
                    color_discrete_sequence=["#4C72B0"],
                )
                fig_top15.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=400)
                st.plotly_chart(fig_top15, use_container_width=True)

        with an_f2:
            st.markdown("**Curva de Pareto — Concentração de Gasto**")
            df_pareto = metrics.pareto_fornecedores(df_an)
            if not df_pareto.empty:
                df_pareto_top = df_pareto.head(30).copy()
                df_pareto_top["idx"] = range(1, len(df_pareto_top) + 1)
                fig_pareto = px.line(
                    df_pareto_top,
                    x="idx",
                    y="acumulado",
                    markers=True,
                    labels={"idx": "Nº de Fornecedores", "acumulado": "% Gasto Acumulado"},
                    color_discrete_sequence=["#d62728"],
                )
                fig_pareto.add_hline(
                    y=80,
                    line_dash="dash",
                    line_color="gray",
                    annotation_text="80%",
                    annotation_position="right",
                )
                fig_pareto.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=400)
                st.plotly_chart(fig_pareto, use_container_width=True)
                _forn_80 = int((df_pareto["acumulado"] <= 80).sum())
                st.caption(
                    f"**{_forn_80} fornecedor(es)** concentram 80% do gasto total "
                    f"(de {len(df_pareto)} fornecedores ativos)."
                )

        st.markdown("---")

        # ── Seção 4: Análise por Empresa/Setor ──────────────────────────────
        st.markdown("### 🏢 Análise por Empresa")
        df_emp_an = metrics.metricas_por_empresa(df_an)
        if not df_emp_an.empty:
            fig_emp = px.bar(
                df_emp_an.head(15).sort_values("valor_total"),
                x="valor_total",
                y="empresa",
                orientation="h",
                labels={"valor_total": "Valor (R$)", "empresa": ""},
                color_discrete_sequence=["#9467bd"],
            )
            fig_emp.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=350)
            st.plotly_chart(fig_emp, use_container_width=True)

            df_emp_display = df_emp_an.copy()
            df_emp_display.columns = ["Empresa", "Qtd.", "Valor Total (R$)", "Ticket Médio (R$)"]
            df_emp_display["Valor Total (R$)"] = df_emp_display["Valor Total (R$)"].apply(format_currency)
            df_emp_display["Ticket Médio (R$)"] = df_emp_display["Ticket Médio (R$)"].apply(format_currency)
            st.dataframe(df_emp_display, use_container_width=True, hide_index=True)

        st.markdown("---")

        # ── Seção 5: Análise por Projeto ────────────────────────────────────
        st.markdown("### 📁 Análise por Projeto")
        df_proj_an = metrics.metricas_por_projeto(df_an)
        _df_proj_validos = df_proj_an.dropna(subset=["projeto"])
        _df_proj_validos = _df_proj_validos[_df_proj_validos["projeto"].str.strip() != ""]
        if not _df_proj_validos.empty:
            an_p1, an_p2 = st.columns(2)
            with an_p1:
                fig_proj = px.bar(
                    _df_proj_validos.head(10).sort_values("valor_total"),
                    x="valor_total",
                    y="projeto",
                    orientation="h",
                    labels={"valor_total": "Valor (R$)", "projeto": ""},
                    color_discrete_sequence=["#e377c2"],
                )
                fig_proj.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=300)
                st.plotly_chart(fig_proj, use_container_width=True)
            with an_p2:
                df_proj_display = _df_proj_validos.copy()
                df_proj_display.columns = ["Projeto", "Qtd.", "Valor Total (R$)"]
                df_proj_display["Valor Total (R$)"] = df_proj_display["Valor Total (R$)"].apply(format_currency)
                st.dataframe(df_proj_display, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum projeto identificado nos dados.")

        st.markdown("---")

        # ── Seção 6: Indicadores de Prazo ───────────────────────────────────
        st.markdown("### ⏱️ Indicadores de Prazo")
        an_t1, an_t2 = st.columns(2)

        with an_t1:
            st.markdown("**Distribuição do Tempo de Atendimento (dias)**")
            dias_serie = metrics.distribuicao_tempo(df_an)
            if not dias_serie.empty:
                fig_hist = px.histogram(
                    dias_serie,
                    nbins=30,
                    labels={"value": "Dias", "count": "Nº Requisições"},
                    color_discrete_sequence=["#17becf"],
                )
                fig_hist.update_layout(
                    showlegend=False,
                    margin=dict(l=0, r=0, t=10, b=0),
                    height=280,
                    xaxis_title="Dias até a compra",
                    yaxis_title="Quantidade",
                )
                st.plotly_chart(fig_hist, use_container_width=True)
                st.caption(
                    f"Mínimo: {int(dias_serie.min())} dias | "
                    f"Mediana: {int(dias_serie.median())} dias | "
                    f"Máximo: {int(dias_serie.max())} dias"
                )
            else:
                st.info("Sem registros com data de solicitação e compra preenchidas.")

        with an_t2:
            st.markdown("**Tempo Médio por Fornecedor**")
            df_tempo_forn = metrics.tempo_por_fornecedor(df_an)
            if not df_tempo_forn.empty:
                df_tf_display = df_tempo_forn.head(15).copy()
                fig_tf = px.bar(
                    df_tf_display.sort_values("tempo_medio_dias"),
                    x="tempo_medio_dias",
                    y="fornecedor",
                    orientation="h",
                    labels={"tempo_medio_dias": "Dias (média)", "fornecedor": ""},
                    color_discrete_sequence=["#bcbd22"],
                )
                fig_tf.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=280)
                st.plotly_chart(fig_tf, use_container_width=True)
            else:
                st.info("Sem dados de prazo por fornecedor.")

        st.markdown("---")

        # ── Seção 7: Tabela completa ─────────────────────────────────────────
        with st.expander("📋 Tabela Completa de Dados", expanded=False):
            display_cols = [c for c in COLUMN_ORDER if c in df_an.columns]
            st.dataframe(df_an[display_cols], use_container_width=True, hide_index=True)


# ---- Projetos ----
if "projetos" in TABS:
  with TABS["projetos"]:
    st.subheader("Projetos")

    # ── Criar novo projeto ────────────────────────────────────────────────
    with st.expander("➕ Criar novo projeto", expanded=False):
        with st.form("form_criar_projeto", clear_on_submit=True):
            _pnome = st.text_input("Nome do projeto *", placeholder="Ex: OBRA NORTE 2024")
            _pdesc = st.text_area("Descrição (opcional)", height=80)
            if st.form_submit_button("Criar projeto", use_container_width=True):
                _pnome_clean = _pnome.strip().upper()
                if not _pnome_clean:
                    st.error("Nome do projeto é obrigatório.")
                elif _pnome_clean in [p.upper() for p in crud.list_projetos()]:
                    st.warning(f"Projeto '{_pnome_clean}' já existe.")
                else:
                    crud.create_projeto(_pnome_clean, _pdesc)
                    st.toast(f"Projeto '{_pnome_clean}' criado.", icon="✅")
                    st.rerun()

    all_projetos = crud.fetch_all_projetos()

    if not all_projetos:
        st.info("Nenhum projeto cadastrado. Use o painel acima para criar o primeiro projeto.")
    else:
        # ── Layout: lista à esquerda | detalhe à direita ──────────────────
        col_lista, col_detalhe = st.columns([1, 2])

        with col_lista:
            st.markdown("**Projetos cadastrados**")
            _proj_nomes = [p["nome"] for p in all_projetos]
            projeto_sel_idx = st.radio(
                "Selecionar",
                range(len(_proj_nomes)),
                format_func=lambda i: _proj_nomes[i],
                label_visibility="collapsed",
                key="projeto_radio_sel",
            )
            projeto_sel_dict = all_projetos[projeto_sel_idx]

        with col_detalhe:
            _psel_nome = projeto_sel_dict["nome"]
            _psel_id   = projeto_sel_dict["id"]
            _psel_desc = projeto_sel_dict.get("descricao") or ""
            _psel_data = projeto_sel_dict.get("criado_em", "")

            reqs_projeto = crud.fetch_requisicoes_por_projeto(_psel_nome)
            orcs_projeto = crud.fetch_orcamentos_por_projeto(_psel_nome)

            df_reqs_p = pd.DataFrame(reqs_projeto)

            # Métricas do projeto
            _total_val = 0.0
            _status_counts: dict = {}
            if not df_reqs_p.empty:
                _total_val = float(
                    (df_reqs_p["valor"].fillna(0) - df_reqs_p["valor_desconto"].fillna(0)).sum()
                )
                _status_counts = df_reqs_p["situacao"].value_counts().to_dict()

            st.markdown(f"### 📁 {_psel_nome}")
            if _psel_desc:
                st.caption(_psel_desc)
            if _psel_data:
                st.caption(f"Criado em: {_psel_data[:10]}")

            _pm1, _pm2, _pm3 = st.columns(3)
            _pm1.metric("Requisições", len(reqs_projeto))
            _pm2.metric("Orçamentos", len(orcs_projeto))
            _pm3.metric("Total gasto", format_currency(_total_val))

            # Breakdown de status
            if _status_counts:
                _status_str = "  ·  ".join(
                    f"{st_}: {cnt}" for st_, cnt in sorted(_status_counts.items())
                )
                st.caption(f"Status: {_status_str}")

            st.markdown("---")

            # Editar projeto
            with st.expander("✏️ Editar projeto", expanded=False):
                with st.form(f"form_editar_projeto_{_psel_id}"):
                    _edit_nome = st.text_input("Nome", value=_psel_nome)
                    _edit_desc = st.text_area("Descrição", value=_psel_desc, height=80)
                    _col_save, _col_del = st.columns(2)
                    _save = _col_save.form_submit_button("💾 Salvar", use_container_width=True)
                    _del  = _col_del.form_submit_button(
                        "🗑️ Excluir projeto", use_container_width=True, type="secondary"
                    )
                    if _save:
                        _edit_nome_clean = _edit_nome.strip().upper()
                        if not _edit_nome_clean:
                            st.error("Nome não pode ser vazio.")
                        else:
                            crud.update_projeto(_psel_id, _edit_nome_clean, _edit_desc)
                            st.toast("Projeto atualizado.", icon="✅")
                            st.rerun()
                    if _del:
                        crud.delete_projeto(_psel_id, _psel_nome)
                        st.toast(f"Projeto '{_psel_nome}' excluído. Requisições desvinculadas.", icon="🗑️")
                        st.rerun()

            # Tabela de requisições
            st.markdown("#### Requisições do projeto")
            if df_reqs_p.empty:
                st.info("Nenhuma requisição vinculada a este projeto ainda.")
            else:
                _display_cols = [c for c in [
                    "id", "data_solicitacao", "empresa", "item",
                    "fornecedor", "valor", "situacao",
                ] if c in df_reqs_p.columns]
                _df_show = df_reqs_p[_display_cols].copy()
                for _dc in ["data_solicitacao", "data_compra"]:
                    if _dc in _df_show.columns:
                        _df_show[_dc] = pd.to_datetime(_df_show[_dc], errors="coerce").dt.strftime("%d/%m/%Y").fillna("")
                st.dataframe(_df_show, use_container_width=True, hide_index=True)

            # Tabela de orçamentos
            st.markdown("#### Orçamentos consolidados")
            if not orcs_projeto:
                st.info("Nenhum orçamento registrado para este projeto.")
            else:
                _df_orcs = pd.DataFrame(orcs_projeto)
                _orc_cols = [c for c in ["id", "item", "empresa", "fornecedor", "valor", "status_orcamento", "prazo_entrega"] if c in _df_orcs.columns]
                _df_orcs_show = _df_orcs[_orc_cols].copy()
                if "valor" in _df_orcs_show.columns:
                    _df_orcs_show["valor"] = _df_orcs_show["valor"].apply(format_currency)
                if "prazo_entrega" in _df_orcs_show.columns:
                    _df_orcs_show["prazo_entrega"] = _df_orcs_show["prazo_entrega"].apply(fmt_date)
                st.dataframe(_df_orcs_show, use_container_width=True, hide_index=True)


# ---- Importar ----
if "importar" in TABS:
  with TABS["importar"]:
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
                registrar_log("IMPORTOU", detalhe=f"{quantidade} registros")
                st.success(f"{quantidade} registros importados com sucesso.")
                st.warning("Importação não remove duplicatas automaticamente.")
                if total_after < total_before:
                    st.info(
                        f"{total_before - total_after} linha(s) ignorada(s) por falta de "
                        "Empresa, Item ou Data Solicitação (campos obrigatórios)."
                    )
            else:
                st.info("Nenhum registro encontrado para importar.")


# ---- Atividades (log global) — Gestor e ADM ----
if "atividades" in TABS:
  with TABS["atividades"]:
    st.subheader("🗒️ Atividades recentes")
    st.caption("Histórico de ações registradas no sistema (mais recentes primeiro).")
    _eventos = crud.list_eventos(limit=500)
    if _eventos:
        _df_ev = pd.DataFrame(_eventos)
        _df_ev["created_at"] = pd.to_datetime(_df_ev["created_at"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M")
        _df_ev = _df_ev.rename(columns={
            "created_at": "Data/Hora", "usuario": "Usuário", "papel": "Papel",
            "acao": "Ação", "entidade": "Entidade", "entidade_id": "ID", "detalhe": "Detalhe",
        })
        st.dataframe(_df_ev, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma atividade registrada ainda.")


# ---- Painel Admin — somente ADM ----
if "admin" in TABS:
  with TABS["admin"]:
    st.subheader("⚙️ Painel do Administrador")

    st.markdown("#### 🔌 Conexão / Banco")
    _is_sqlite = is_sqlite_url(database_url)
    _ac1, _ac2, _ac3 = st.columns(3)
    _ac1.metric("Banco", "SQLite (efêmero)" if _is_sqlite else "PostgreSQL")
    _ac2.metric("Requisições", crud.count_requisicoes({}))
    _ac3.metric("Usuários", crud.count_usuarios())
    if _is_sqlite:
        st.warning("Banco SQLite: dados não persistem em deploy. Configure DATABASE_URL (Postgres).")
    else:
        st.success("PostgreSQL conectado — dados persistentes.")

    st.markdown("---")
    st.markdown("#### 👥 Usuários")
    _usuarios = crud.list_usuarios()
    if _usuarios:
        _dfu = pd.DataFrame(_usuarios)[["id", "nome", "login", "papel", "ativo", "created_at"]]
        _dfu["ativo"] = _dfu["ativo"].apply(lambda v: "Sim" if v else "Não")
        _dfu["created_at"] = pd.to_datetime(_dfu["created_at"], errors="coerce").dt.strftime("%d/%m/%Y %H:%M").fillna("")
        st.dataframe(
            _dfu, use_container_width=True, hide_index=True,
            column_config={"created_at": st.column_config.TextColumn("Criado em")},
        )

    with st.expander("➕ Criar usuário", expanded=False):
        _n = st.text_input("Nome", key="adm_novo_nome")
        _l = st.text_input("Login", key="adm_novo_login")
        _s = st.text_input("Senha provisória", type="password", key="adm_novo_senha")
        _p = st.selectbox("Papel", auth.PAPEIS, format_func=lambda p: auth.PAPEL_LABEL[p], key="adm_novo_papel")
        if st.button("Criar usuário", use_container_width=True, type="primary", key="adm_btn_criar"):
            if not (_n.strip() and _l.strip() and _s):
                st.error("Preencha nome, login e senha.")
            elif crud.get_usuario_por_login(_l):
                st.error("Já existe um usuário com esse login.")
            elif run_safe(crud.create_usuario, _n, _l, _s, _p, sucesso="Usuário criado."):
                registrar_log("CRIOU_USUARIO", "usuario", detalhe=_l)
                st.rerun()

    with st.expander("✏️ Editar / Resetar senha / Ativar-Desativar", expanded=False):
        if _usuarios:
            _alvo = st.selectbox(
                "Usuário", options=[u["id"] for u in _usuarios],
                format_func=lambda i: next((f"{u['nome']} ({u['login']})" for u in _usuarios if u["id"] == i), str(i)),
                key="adm_edit_alvo",
            )
            _u_sel = next((u for u in _usuarios if u["id"] == _alvo), None)
            if _u_sel:
                _ep = st.selectbox("Papel", auth.PAPEIS, index=auth.PAPEIS.index(_u_sel["papel"]) if _u_sel["papel"] in auth.PAPEIS else 0,
                                   format_func=lambda p: auth.PAPEL_LABEL[p], key="adm_edit_papel")
                _ea = st.checkbox("Ativo", value=bool(_u_sel["ativo"]), key="adm_edit_ativo")
                _ecol1, _ecol2 = st.columns(2)
                if _ecol1.button("Salvar alterações", use_container_width=True, key="adm_btn_salvar"):
                    if run_safe(crud.update_usuario, int(_alvo), {"papel": _ep, "ativo": 1 if _ea else 0},
                                sucesso="Usuário atualizado."):
                        registrar_log("EDITOU_USUARIO", "usuario", int(_alvo))
                        st.rerun()
                _nova = _ecol2.text_input("Nova senha", type="password", key="adm_reset_senha")
                if _ecol2.button("Resetar senha", use_container_width=True, key="adm_btn_reset"):
                    if not _nova:
                        st.error("Informe a nova senha.")
                    elif run_safe(crud.set_senha, int(_alvo), _nova, sucesso="Senha redefinida."):
                        registrar_log("RESETOU_SENHA", "usuario", int(_alvo))
                        st.rerun()
