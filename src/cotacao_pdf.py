"""Importação de 'Carta de Cotação' (PDF) → requisição.

Lê o PDF gerado pela plataforma oficial de compras e extrai os dados
necessários para criar uma requisição com seus itens.
"""

from __future__ import annotations

import io
import re
from typing import Any


def _parse_qtde(texto: str) -> tuple[float | None, str]:
    """'1.200,00 PC' -> (1200.0, 'PC'). Retorna (quantidade, unidade)."""
    if not texto:
        return None, ""
    m = re.match(r"\s*([\d.,]+)\s*([A-Za-zºª]+)?", texto.strip())
    if not m:
        return None, ""
    num_raw, unidade = m.group(1), (m.group(2) or "").strip()
    num = num_raw.replace(".", "").replace(",", ".")
    try:
        return float(num), unidade.upper()
    except ValueError:
        return None, unidade.upper()


def _br_to_iso(data_br: str | None) -> str | None:
    """'17/06/2026' -> '2026-06-17'."""
    if not data_br:
        return None
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", data_br.strip())
    if not m:
        return None
    d, mth, y = m.groups()
    return f"{y}-{mth}-{d}"


def _extrair_itens(page) -> list[dict[str, Any]]:
    """Extrai os itens da tabela 'Relação de Produtos'."""
    itens: list[dict[str, Any]] = []
    try:
        tabelas = page.find_tables()
    except Exception:  # noqa: BLE001
        return itens

    for tab in tabelas.tables:
        linhas = tab.extract()
        if not linhas:
            continue
        cabecalho = [str(c or "").strip().lower() for c in linhas[0]]
        if "descrição" not in cabecalho and "descricao" not in cabecalho:
            continue
        # Índices das colunas pelo cabeçalho
        def _idx(nome: str, default: int) -> int:
            for i, c in enumerate(cabecalho):
                if nome in c:
                    return i
            return default
        i_item, i_cod, i_desc, i_qtd = (
            _idx("item", 0), _idx("código", 1), _idx("descri", 2), _idx("quant", 3)
        )

        for row in linhas[1:]:
            cell = lambda i: str(row[i] or "").strip() if i < len(row) else ""
            item_n, cod, desc, qtd = cell(i_item), cell(i_cod), cell(i_desc), cell(i_qtd)
            if not any((item_n, cod, desc, qtd)):
                continue  # linha vazia
            if item_n:  # novo item
                quantidade, unidade = _parse_qtde(qtd)
                itens.append({
                    "codigo": cod,
                    "descricao": desc,
                    "quantidade": quantidade,
                    "unidade": unidade,
                    "valor_unitario": None,
                    "observacao": "",
                })
            elif itens:  # linha de continuação do item anterior
                if cod:
                    itens[-1]["codigo"] = f"{itens[-1]['codigo']}{cod}".strip()
                if desc:
                    itens[-1]["descricao"] = f"{itens[-1]['descricao']} {desc}".strip()
        break  # usa apenas a primeira tabela de produtos
    return itens


def parse_carta_cotacao(file_bytes: bytes) -> dict[str, Any]:
    """Lê os bytes de um PDF de Carta de Cotação e devolve os dados da requisição.

    Retorna dict com: requisicao, empresa, data_solicitacao (ISO), entrega,
    projeto, item (resumo), itens[], e 'erros' (lista de avisos).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "PyMuPDF (fitz) não está instalado. Adicione 'PyMuPDF' ao requirements.txt."
        ) from exc

    erros: list[str] = []
    doc = fitz.open(stream=io.BytesIO(file_bytes), filetype="pdf")
    page = doc[0]
    texto = page.get_text("text")

    def _busca(padrao: str) -> str | None:
        m = re.search(padrao, texto, re.IGNORECASE)
        return m.group(1).strip() if m else None

    numero = _busca(r"Carta de Cota[çc][ãa]o\s*N[ºo°]\s*([0-9]+)")
    data_inc = _busca(r"inclu[íi]do em:\s*(\d{2}/\d{2}/\d{4})")
    entrega = _busca(r"Sugest[ãa]o de Entrega:\s*([^\n]+)")
    projeto = _busca(r"Projeto:\s*([^\n]+)")

    # Empresa: primeira linha não vazia do cabeçalho
    empresa = ""
    for linha in texto.splitlines():
        if linha.strip():
            empresa = linha.strip()
            break
    # Encurta para o primeiro nome (ex.: 'ENGEMETAL COMERCIO...' -> 'ENGEMETAL')
    empresa_curta = empresa.split()[0].upper() if empresa else ""

    itens = _extrair_itens(page)
    if not itens:
        erros.append("Nenhum item encontrado na 'Relação de Produtos'.")

    data_iso = _br_to_iso(data_inc)
    if data_inc and not data_iso:
        erros.append(f"Data de inclusão não reconhecida: {data_inc}")

    # Resumo do item para a coluna 'Item' da lista
    if itens:
        primeiro = itens[0]["descricao"] or itens[0]["codigo"]
        resumo = primeiro if len(itens) == 1 else f"{primeiro} (+{len(itens) - 1} itens)"
    else:
        resumo = f"Carta de Cotação {numero}" if numero else "Carta de Cotação"

    return {
        "requisicao": numero,
        "empresa": empresa_curta,
        "empresa_completa": empresa,
        "data_solicitacao": data_iso,
        "entrega": (entrega or "").strip(),
        "projeto": (projeto or "").strip(),
        "item": resumo,
        "itens": itens,
        "erros": erros,
    }
