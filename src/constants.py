"""Constantes do sistema."""

PIN_ACESSO = "@Compras"

STATUS_LIST = ["Solicitado", "Comprado", "Entregue", "Cancelado"]

COLUMN_MAP = {
    "empresa": "empresa",
    "setor": "setor",
    "requisicao": "requisicao",
    "req": "requisicao",
    "data_solicitacao": "data_solicitacao",
    "datasolicitacao": "data_solicitacao",
    "data_solicitacao_compra": "data_solicitacao",
    "data_compra": "data_compra",
    "datacompra": "data_compra",
    "fornecedor": "fornecedor",
    "qtde": "qtde",
    "quantidade": "qtde",
    "item": "item",
    "entrega": "entrega",
    "situacao": "situacao",
    "situacao_status": "situacao",
    "valor": "valor",
    "valor_desconto": "valor_desconto",
    "valordesconto": "valor_desconto",
    "nf": "nf",
    "nota_fiscal": "nf",
    "observacao": "observacao",
    "observacoes": "observacao",
}

COLUMN_ORDER = [
    "empresa",
    "setor",
    "requisicao",
    "data_solicitacao",
    "data_compra",
    "fornecedor",
    "qtde",
    "item",
    "entrega",
    "situacao",
    "valor",
    "valor_desconto",
    "nf",
    "observacao",
]

DISPLAY_NAMES = {
    "empresa": "Empresa",
    "setor": "Setor",
    "requisicao": "Requisição",
    "data_solicitacao": "Data Solicitação",
    "data_compra": "Data Compra",
    "fornecedor": "Fornecedor",
    "qtde": "Qtde",
    "item": "Item",
    "entrega": "Entrega",
    "situacao": "Situação",
    "valor": "Valor",
    "valor_desconto": "Valor Desconto",
    "nf": "NF",
    "observacao": "Observação",
}
