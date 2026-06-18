"""Autenticação simples via PIN."""

from __future__ import annotations

import streamlit as st

from .constants import PIN_ACESSO


def require_pin() -> bool:
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    st.title("Acesso")
    pin = st.text_input("Digite o PIN", type="password")
    if st.button("Entrar"):
        if pin == PIN_ACESSO:
            st.session_state.authenticated = True
            st.success("Acesso liberado.")
            st.rerun()
        else:
            st.error("PIN incorreto.")
    return False
