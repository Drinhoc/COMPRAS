"""Importação de documentos da plataforma de compras (PDF) → requisição.

Reconhece dois tipos de documento e extrai os dados para criar uma requisição
com seus itens:
  - 'Carta de Cotação'  → requisição em 'Solicitado' (sem preços)
  - 'Pedido de Compra'  → requisição em 'Comprado' (com fornecedor e valores)
"""

from __future__ import annotations

import io
import re
from typing import Any


def _parse_qtde(texto: str) -> tuple[float | None, str]:
    """'8,00 UN' -> (8.0, 'UN'). Retorna (quantidade, unidade)."""
    if not texto:
        return None, ""
    m = re.match(r"\s*([\d.,]+)\s*([A-Za-zºª/]+)?", texto.strip())
    if not m:
        return None, ""
    num = m.group(1).replace(".", "").replace(",", ".")
    unidade = (m.group(2) or "").strip().upper()
    try:
        return float(num), unidade
    except ValueError:
        return None, unidade


def _parse_money(texto: object) -> float | None:
    """'1.992,00' -> 1992.0 ; '249,000' -> 249.0."""
    if texto in (None, ""):
        return None
    s = str(texto).strip()
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


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
    """Extrai os itens da tabela de produtos (Cotação ou Pedido)."""
    itens: list[dict[str, Any]] = []
    try:
        tabelas = page.find_tables()
    except Exception:  # noqa: BLE001
        return itens

    for tab in tabelas.tables:
        linhas = tab.extract()
        if not linhas:
            continue
        cab = [str(c or "").strip().lower() for c in linhas[0]]
        if not any("descri" in c for c in cab):
            continue

        def _idx(*nomes: str) -> int:
            for i, c in enumerate(cab):
                if any(n in c for n in nomes):
                    return i
            return -1

        i_item = _idx("item")
        i_cod = _idx("código", "codigo")
        i_desc = _idx("descri")
        i_qtd = _idx("quant")
        i_vu = _idx("valor unit", "vlr unit", "unit")
        i_vt = _idx("valor total", "vlr total")

        def cell(row, i):
            return str(row[i] or "").strip() if 0 <= i < len(row) else ""

        for row in linhas[1:]:
            item_n = cell(row, i_item)
            cod = cell(row, i_cod)
            desc = cell(row, i_desc)
            qtd = cell(row, i_qtd)
            # Ignora linhas de totais (Subtotal/Total/Desconto) e linhas vazias
            if not item_n and not desc and not cod:
                continue
            if re.match(r"(sub)?total|desconto|ipi|icms", desc, re.IGNORECASE):
                continue
            if item_n:  # novo item
                quantidade, unidade = _parse_qtde(qtd)
                itens.append({
                    "codigo": cod,
                    "descricao": desc,
                    "quantidade": quantidade,
                    "unidade": unidade,
                    "valor_unitario": _parse_money(cell(row, i_vu)) if i_vu >= 0 else None,
                    "valor_total": _parse_money(cell(row, i_vt)) if i_vt >= 0 else None,
                    "observacao": "",
                })
            elif itens:  # continuação do item anterior
                if cod:
                    itens[-1]["codigo"] = f"{itens[-1]['codigo']}{cod}".strip()
                if desc:
                    itens[-1]["descricao"] = f"{itens[-1]['descricao']} {desc}".strip()
        break
    return itens


def _empresa_curta(texto: str) -> tuple[str, str]:
    """Primeira linha não vazia (razão social) + nome curto."""
    empresa = ""
    for linha in texto.splitlines():
        if linha.strip():
            empresa = linha.strip()
            break
    curta = empresa.split()[0].upper() if empresa else ""
    return curta, empresa


def _resumo_item(itens: list[dict], numero: str | None, rotulo: str) -> str:
    if itens:
        primeiro = itens[0]["descricao"] or itens[0]["codigo"]
        return primeiro if len(itens) == 1 else f"{primeiro} (+{len(itens) - 1} itens)"
    return f"{rotulo} {numero}" if numero else rotulo


def parse_documento(file_bytes: bytes) -> dict[str, Any]:
    """Detecta o tipo de PDF e devolve os dados da requisição.

    Sempre retorna dict com chave 'tipo' ('cotacao' | 'pedido') e os campos
    correspondentes, além de 'itens' e 'erros'.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "PyMuPDF (fitz) não está instalado. Adicione 'PyMuPDF' ao requirements.txt."
        ) from exc

    doc = fitz.open(stream=io.BytesIO(file_bytes), filetype="pdf")
    page = doc[0]
    texto = page.get_text("text")

    if re.search(r"Pedido de Compra\s*N", texto, re.IGNORECASE):
        return _parse_pedido(page, texto)
    return _parse_cotacao(page, texto)


def _busca(texto: str, padrao: str) -> str | None:
    m = re.search(padrao, texto, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _parse_cotacao(page, texto: str) -> dict[str, Any]:
    erros: list[str] = []
    numero = _busca(texto, r"Carta de Cota[çc][ãa]o\s*N[ºo°]\s*([0-9]+)")
    data_inc = _busca(texto, r"inclu[íi]do em:\s*(\d{2}/\d{2}/\d{4})")
    entrega = _busca(texto, r"Sugest[ãa]o de Entrega:\s*([^\n]+)")
    curta, completa = _empresa_curta(texto)

    itens = _extrair_itens(page)
    if not itens:
        erros.append("Nenhum item encontrado na 'Relação de Produtos'.")
    data_iso = _br_to_iso(data_inc)
    if data_inc and not data_iso:
        erros.append(f"Data de inclusão não reconhecida: {data_inc}")

    return {
        "tipo": "cotacao",
        "requisicao": numero,
        "empresa": curta,
        "empresa_completa": completa,
        "fornecedor": "",
        "data_solicitacao": data_iso,
        "data_compra": None,
        "entrega": (entrega or "").strip(),
        "situacao": "Solicitado",
        "valor": None,
        "valor_desconto": None,
        "observacao": "",
        "item": _resumo_item(itens, numero, "Carta de Cotação"),
        "itens": itens,
        "erros": erros,
    }


def _parse_pedido(page, texto: str) -> dict[str, Any]:
    erros: list[str] = []
    numero = _busca(texto, r"Pedido de Compra\s*N[ºo°]\s*([0-9]+)")
    data_inc = _busca(texto, r"inclu[íi]do em:\s*(\d{2}/\d{2}/\d{4})")
    entrega = _busca(texto, r"Previs[ãa]o de Entrega:\s*([^\n]+)")
    fornecedor = _busca(texto, r"Informa[çc][õo]es do Fornecedor\s*\n([^\n]+)")
    contato = _busca(texto, r"Contato:\s*([^\n]+)")
    parcelas = _busca(texto, r"Parcelas\s*\n([^\n]+)")
    total = _parse_money(_busca(texto, r"\nTotal:\s*\(R\$\)\s*\n([\d.,]+)"))
    desconto = _parse_money(_busca(texto, r"Desconto:\s*\(R\$\)\s*\n([\d.,]+)"))
    curta, completa = _empresa_curta(texto)

    itens = _extrair_itens(page)
    if not itens:
        erros.append("Nenhum item encontrado em 'Itens do Pedido'.")
    data_iso = _br_to_iso(data_inc)
    if data_inc and not data_iso:
        erros.append(f"Data de inclusão não reconhecida: {data_inc}")

    # Total: usa o do PDF; se faltar, soma os totais dos itens.
    if total is None:
        soma = sum(it["valor_total"] for it in itens if it.get("valor_total"))
        total = soma or None

    obs_partes = []
    if parcelas:
        obs_partes.append(f"Pgto: {parcelas}")
    if contato:
        obs_partes.append(f"Contato: {contato}")

    return {
        "tipo": "pedido",
        "requisicao": numero,
        "empresa": curta,
        "empresa_completa": completa,
        "fornecedor": (fornecedor or "").strip(),
        "data_solicitacao": data_iso,
        "data_compra": data_iso,
        "entrega": (entrega or "").strip(),
        "situacao": "Comprado",
        "valor": total,
        "valor_desconto": desconto,
        "observacao": " · ".join(obs_partes),
        "item": _resumo_item(itens, numero, "Pedido de Compra"),
        "itens": itens,
        "erros": erros,
    }


# Compatibilidade: nome antigo usado anteriormente.
def parse_carta_cotacao(file_bytes: bytes) -> dict[str, Any]:
    return parse_documento(file_bytes)
