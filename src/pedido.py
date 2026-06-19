"""Gerador de Pedido de Compra em PDF (reportlab).

Reaproveita logos e dados cadastrais das empresas (Engemetal/Bluesun e
Engecomp) extraídos dos modelos oficiais, com um layout reconstruído.
"""

from __future__ import annotations

import io
import os
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")

# Cor de destaque por empresa
_VERDE = colors.HexColor("#3FB618")
_AZUL = colors.HexColor("#1F3864")

# Perfis das empresas emissoras do pedido.
EMPRESAS: dict[str, dict[str, Any]] = {
    "ENGEMETAL": {
        "logo": "logo_bluesun.png",
        "cor": _VERDE,
        "razao_social": "ENGEMETAL COMÉRCIO E MANUTENÇÃO LTDA.",
        "linhas": [
            "Avenida Vitorino Arigone, 450 – Jardim Santa Bárbara",
            "CEP: 13480-309 — Limeira/SP",
            "CNPJ: 10.383.997/0001-60   I.E: 417.189.790.114",
            "Telefone: (19) 3443-8228   Celular: (19) 99331-2871 (WhatsApp)",
            "Boleto e NF para: nfe@bluesundobrasil.com.br",
        ],
        "email_nf": "nfe@bluesundobrasil.com.br",
        "assinatura": "COMPRAS — Bluesun do Brasil",
    },
    "ENGECOMP": {
        "logo": "logo_engecomp.png",
        "cor": _AZUL,
        "razao_social": "ENGECOMP REFRIGERAÇÃO INDUSTRIAL LTDA.",
        "linhas": [
            "Avenida Vitorino Arigone, 450 – Jardim Santa Bárbara",
            "CEP: 13480-309 — Limeira/SP",
            "CNPJ: 02.817.917/0001-09   I.E: 135.989.199.117",
            "Boleto e NF para: nfe@engecomprefrigeracao.com.br",
        ],
        "email_nf": "nfe@engecomprefrigeracao.com.br",
        "assinatura": "COMPRAS — Engecomp Refrigeração Industrial",
    },
}


def _brl(value: object) -> str:
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        return "R$ 0,00"
    return "R$ " + f"{num:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_pedido_pdf(empresa_key: str, pedido: dict[str, Any]) -> bytes:
    """Gera o PDF do pedido de compra.

    `pedido` aceita as chaves:
        numero, data, destinatario{empresa,ac,email,cnpj,endereco,cidade,cep},
        itens[{quant,descricao,valor_unit,prazo}], desconto, condicoes_pagamento,
        entrega, observacoes, assinatura
    """
    empresa = EMPRESAS.get(empresa_key, EMPRESAS["ENGEMETAL"])
    cor = empresa["cor"]
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=styles["Normal"], fontSize=8.5, leading=11)
    small = ParagraphStyle("s", parent=normal, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#555555"))
    lbl = ParagraphStyle("l", parent=normal, fontSize=8, textColor=colors.HexColor("#444444"))
    h_title = ParagraphStyle("t", parent=normal, fontSize=15, leading=18, textColor=cor, spaceAfter=2)
    cell = ParagraphStyle("c", parent=normal, fontSize=8.5, leading=10.5)
    cell_c = ParagraphStyle("cc", parent=cell, alignment=1)
    cell_r = ParagraphStyle("cr", parent=cell, alignment=2)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=12 * mm, bottomMargin=14 * mm,
        title=f"Pedido {pedido.get('numero', '')}",
    )
    elems: list = []

    # ── Cabeçalho: logo + dados da empresa ────────────────────────────────
    logo_path = os.path.join(ASSETS_DIR, empresa["logo"])
    logo_flow: Any = ""
    if os.path.exists(logo_path):
        img = Image(logo_path)
        ratio = img.imageHeight / float(img.imageWidth)
        # Encaixa o logo numa faixa de cabeçalho consistente entre as empresas:
        # limita largura E altura preservando a proporção (evita logo quadrado gigante).
        max_w, max_h = 42 * mm, 20 * mm
        w = max_w
        h = w * ratio
        if h > max_h:
            h = max_h
            w = h / ratio
        img.drawWidth = w
        img.drawHeight = h
        logo_flow = img

    dados = [Paragraph(f"<b>{empresa['razao_social']}</b>", normal)]
    dados += [Paragraph(linha, small) for linha in empresa["linhas"]]

    head = Table([[logo_flow, dados]], colWidths=[50 * mm, 130 * mm])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elems += [head, Spacer(1, 4)]
    elems += [_linha(cor), Spacer(1, 6)]

    # ── Título + número/data ──────────────────────────────────────────────
    titulo = Table(
        [[Paragraph("PEDIDO DE COMPRA", h_title),
          Paragraph(
              f"<b>Nº {pedido.get('numero', '—')}</b><br/>"
              f"Data: {pedido.get('data', '—')}", cell_r)]],
        colWidths=[120 * mm, 60 * mm],
    )
    titulo.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    elems += [titulo, Spacer(1, 6)]

    # ── Destinatário (fornecedor) ─────────────────────────────────────────
    d = pedido.get("destinatario", {})

    def _campo(rotulo: str, valor: str) -> Paragraph:
        return Paragraph(f"<b>{rotulo}:</b> {valor or '—'}", lbl)

    dest = Table(
        [
            [_campo("À (Fornecedor)", d.get("empresa", "")), _campo("A/C", d.get("ac", ""))],
            [_campo("CNPJ", d.get("cnpj", "")), _campo("E-mail", d.get("email", ""))],
            [_campo("Endereço", d.get("endereco", "")), _campo("Cidade", d.get("cidade", ""))],
            [_campo("CEP", d.get("cep", "")), ""],
        ],
        colWidths=[95 * mm, 85 * mm],
    )
    dest.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#BBBBBB")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#E0E0E0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elems += [dest, Spacer(1, 8)]

    # ── Tabela de itens ───────────────────────────────────────────────────
    header = ["Quant.", "Item / Descrição", "Valor Unit.", "Valor Total", "Prazo de entrega"]
    linhas = [[Paragraph(f"<b>{h}</b>", cell_c if i != 1 else cell) for i, h in enumerate(header)]]
    subtotal = 0.0
    for it in pedido.get("itens", []):
        try:
            q = float(it.get("quant") or 0)
        except (TypeError, ValueError):
            q = 0
        try:
            vu = float(it.get("valor_unit") or 0)
        except (TypeError, ValueError):
            vu = 0
        total = q * vu
        subtotal += total
        linhas.append([
            Paragraph(_num(q), cell_c),
            Paragraph(str(it.get("descricao") or ""), cell),
            Paragraph(_brl(vu), cell_r),
            Paragraph(_brl(total), cell_r),
            Paragraph(str(it.get("prazo") or ""), cell_c),
        ])

    tbl = Table(linhas, colWidths=[18 * mm, 82 * mm, 26 * mm, 26 * mm, 28 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), cor),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F7FA")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elems += [tbl]

    # ── Totais ────────────────────────────────────────────────────────────
    desconto = float(pedido.get("desconto") or 0)
    total_final = subtotal - desconto
    tot = Table(
        [
            ["", "Subtotal:", _brl(subtotal)],
            ["", "Desconto:", _brl(desconto)],
            ["", "TOTAL DO PEDIDO:", _brl(total_final)],
        ],
        colWidths=[100 * mm, 50 * mm, 30 * mm],
    )
    tot.setStyle(TableStyle([
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (1, 0), (-1, -1), 9),
        ("FONTNAME", (1, 2), (-1, 2), "Helvetica-Bold"),
        ("TEXTCOLOR", (1, 2), (-1, 2), cor),
        ("LINEABOVE", (1, 2), (-1, 2), 0.6, cor),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elems += [tot, Spacer(1, 8)]

    # ── Condições / observações ───────────────────────────────────────────
    cond_linhas = []
    if pedido.get("entrega"):
        cond_linhas.append(f"<b>Entrega:</b> {pedido['entrega']}")
    if pedido.get("condicoes_pagamento"):
        cond_linhas.append(f"<b>Pagamento:</b> {pedido['condicoes_pagamento']}")
    if pedido.get("observacoes"):
        cond_linhas.append(f"<b>Observações:</b> {pedido['observacoes']}")
    cond_linhas.append(f"<b>Envio de nota:</b> {empresa['email_nf']}")
    cond_html = "<br/>".join(cond_linhas)
    cond = Table([[Paragraph(cond_html, normal)]], colWidths=[180 * mm])
    cond.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#BBBBBB")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FCFCFC")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elems += [cond, Spacer(1, 16)]

    # ── Assinatura ────────────────────────────────────────────────────────
    elems += [
        Paragraph("Atenciosamente,", normal),
        Spacer(1, 12),
        _linha(colors.HexColor("#999999"), largura=70 * mm),
        Paragraph(pedido.get("assinatura") or empresa["assinatura"], normal),
    ]

    doc.build(elems)
    return buf.getvalue()


def _linha(cor, largura: float = 180 * mm):
    t = Table([[""]], colWidths=[largura], rowHeights=[1])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.2, cor)]))
    return t


def _num(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:g}"
