"""Autenticação por usuário/senha e controle de papéis."""

from __future__ import annotations

import streamlit as st

from . import crud

# Mapa CENTRAL de permissões por papel.
# Para refinar autorizações no futuro, basta ajustar aqui.
PERMISSOES: dict[str, dict[str, bool]] = {
    "ADM": {
        "editar": True, "excluir": True, "aprovar": True,
        "admin": True, "logs": False, "ver_financeiro": True, "importar": True,
    },
    "GESTOR": {
        "editar": True, "excluir": False, "aprovar": True,
        "admin": False, "logs": False, "ver_financeiro": True, "importar": False,
    },
    # Início mais permissivo (quase como Gestor), porém pode editar e não vê logs.
    # Aperte as flags abaixo conforme for refinando.
    "COMPRADOR": {
        "editar": True, "excluir": False, "aprovar": True,
        "admin": False, "logs": False, "ver_financeiro": True, "importar": False,
    },
}

PAPEIS = ["ADM", "GESTOR", "COMPRADOR"]
PAPEL_LABEL = {"ADM": "Administrador", "GESTOR": "Gestor", "COMPRADOR": "Comprador"}


def pode(acao: str, user: dict | None = None) -> bool:
    user = user or st.session_state.get("auth_user")
    if not user:
        return False
    return PERMISSOES.get(user.get("papel", ""), {}).get(acao, False)


def current_user() -> dict | None:
    return st.session_state.get("auth_user")


def logout() -> None:
    st.session_state.pop("auth_user", None)


def require_login() -> dict:
    """Garante login. Retorna o usuário logado ou interrompe a página com a tela de login."""
    # Cria ADM inicial se a base estiver sem usuários.
    cred = crud.seed_admin()

    if st.session_state.get("auth_user"):
        return st.session_state["auth_user"]

    st.title("🔐 Acesso ao Sistema de Compras")
    if cred:
        st.info(
            f"Primeiro acesso: usuário **{cred['login']}** / senha **{cred['senha']}** "
            "(ADM). Troque a senha no painel ⚙️ Admin após entrar."
        )

    with st.form("login_form"):
        login = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        ok = st.form_submit_button("Entrar", use_container_width=True, type="primary")
    if ok:
        u = crud.get_usuario_por_login(login)
        if not u or not u.get("ativo"):
            st.error("Usuário não encontrado ou inativo.")
        elif not crud.verificar_senha(senha, u["senha_hash"], u["salt"]):
            st.error("Senha incorreta.")
        else:
            st.session_state["auth_user"] = {
                "id": u["id"], "nome": u["nome"], "login": u["login"], "papel": u["papel"],
            }
            crud.registrar_evento(u["login"], u["papel"], "LOGIN")
            st.rerun()
    st.stop()
