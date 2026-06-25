# Documentação Técnica — Sistema de Controle de Compras

> **Objetivo deste documento:** explicar, de ponta a ponta, **o que o sistema faz**, **como
> está construído** e **como foram tomadas as decisões**, de modo que a equipe de TI possa
> avaliar e **integrar estas funcionalidades à plataforma atual** da empresa, sem precisar
> reconstruir do zero. Cada regra de negócio e cada função relevante estão descritas abaixo.

---

## 1. Visão geral

O sistema é um **controle interno de compras** que acompanha o ciclo:

```
Requisição  →  Cotação (orçamentos)  →  Aprovação  →  Pedido de Compra (PDF)  →  Comprado/Concluído
```

Não substitui a plataforma oficial que **emite** os pedidos — ele é a camada de **controle e
gestão** desses pedidos: registra requisições, anexa orçamentos, aprova, gera/recebe pedidos,
e consolida tudo em dashboards e análises. Ele também **importa PDFs** (Cartas de Cotação e
Pedidos de Compra) gerados pela plataforma oficial, convertendo-os automaticamente em
requisições.

**Importante para a integração:** a lógica de negócio está **separada da interface** (camada
`src/`), então boa parte do código (parsing de PDF, regras de status, cálculos, geração de PDF,
acesso a dados) pode ser **reaproveitada** mesmo trocando o front-end.

---

## 2. Stack tecnológica

| Camada | Tecnologia | Papel |
|---|---|---|
| Linguagem | **Python 3.11+** | Todo o backend e a lógica |
| Interface | **Streamlit** | UI web (telas, abas, formulários) — *única parte acoplada* |
| Acesso a dados | **SQLAlchemy 2.0** (SQL via `text()` parametrizado) | Abstrai SQLite/Postgres |
| Banco | **PostgreSQL** (produção) / **SQLite** (dev) | Persistência |
| Dados/tabelas | **pandas** | Filtros, agregações, métricas |
| Gráficos | **Plotly** | Dashboard e Análises |
| Geração de PDF | **ReportLab** | Pedido de Compra em PDF |
| Leitura de PDF | **PyMuPDF (fitz)** | Importação de cotações/pedidos |
| Planilhas | **openpyxl** | Importação/exportação Excel |

> **Nota de integração:** se a plataforma da empresa **não** for em Python, os pontos mais
> facilmente portáveis são as **regras** (descritas neste doc) e os **algoritmos de parsing de
> PDF** (seção 7). O acesso a dados (`crud.py`) é SQL puro parametrizado, fácil de traduzir.

---

## 3. Arquitetura (camadas)

```
app.py                 → Interface Streamlit (UI). ~2.400 linhas. NÃO contém regra crítica isolável.
.streamlit/config.toml → Tema visual (cores da marca).
assets/                → Logos usadas nos PDFs e no cabeçalho.
src/
 ├── db.py          → Conexão, definição do schema (tabelas) e migrações automáticas.
 ├── constants.py   → Listas de status, mapeamento de colunas, nomes de exibição.
 ├── crud.py        → TODO o acesso a dados (CRUD) + autenticação (hash) + auditoria.
 ├── auth.py        → Login, sessão e o MAPA CENTRAL DE PERMISSÕES por papel.
 ├── metrics.py     → Cálculos e agregações para dashboard/análises (puro pandas).
 ├── excel_io.py    → Importação/exportação Excel + normalização de dados.
 ├── pedido.py      → Geração do Pedido de Compra em PDF (ReportLab).
 └── cotacao_pdf.py → Leitura/parse de PDFs (Carta de Cotação e Pedido de Compra).
```

**Princípio:** `app.py` só orquestra a tela; toda regra de verdade está em `src/`. Para integrar
na plataforma atual, o TI pode chamar as funções de `src/` a partir de outro front-end/serviço.

---

## 4. Modelo de dados

Oito tabelas. Datas são armazenadas como **texto ISO `YYYY-MM-DD`** (ordenável); a exibição em
`DD/MM/AAAA` é feita na apresentação.

### `requisicoes` — entidade central
| Coluna | Tipo | Observação |
|---|---|---|
| id | int PK | |
| empresa | text **(obrigatório)** | Ex.: ENGEMETAL, ENGECOMP |
| setor | text | |
| projeto | text | |
| requisicao | text | **Código original** (nº da carta/pedido da plataforma oficial) |
| data_solicitacao | text ISO **(obrigatório)** | |
| data_compra | text ISO | Preenchida ao virar "Comprado" |
| fornecedor | text | |
| qtde | int | (resumo; o detalhe fica em `itens`) |
| item | text **(obrigatório)** | Descrição-resumo da requisição |
| entrega | text | Prazo/sugestão de entrega |
| situacao | text | Solicitado / Cotação / Aprovação / Comprado / Concluído / Cancelado |
| valor | float | Valor total |
| valor_desconto | float | |
| nf | text | Nota fiscal |
| observacao | text | |
| created_at / updated_at | text | Auditoria |

### `itens` — itens estruturados de uma requisição (1:N)
`id`, `requisicao_id` (FK), `descricao` (obrigatório), `quantidade`, `unidade`, `valor_unitario`, `observacao`.

### `orcamentos` — cotações recebidas (1:N)
`id`, `requisicao_id` (FK), `fornecedor`, `valor`, `prazo_entrega`, `condicoes_pagamento`,
`status_orcamento` (RECEBIDO/APROVADO/APROVADO PARCIAL/REJEITADO), `observacao`, `created_at`.

### `aprovacoes` — histórico de decisões (1:N)
`id`, `requisicao_id` (FK), `orcamento_id` (FK, **opcional** — permite aprovar sem orçamento),
`acao` (APROVADO/APROVADO PARCIAL/REPROVADO/COMENTÁRIO), `comentario`, `aprovador`, `created_at`.

### `anexos` — arquivos (1:N)
`id`, `requisicao_id` (FK), `orcamento_id` (FK opcional), `tipo`, `nome_arquivo`, `mime_type`,
`conteudo` (**binário/BLOB**), `uploaded_at`, `uploaded_by`.

### `projetos`
`id`, `nome` (único), `descricao`, `criado_em`.

### `usuarios` — autenticação
`id`, `nome`, `login` (único), `senha_hash`, `salt`, `papel` (ADM/GESTOR/COMPRADOR), `ativo`, `created_at`.
**Senhas nunca em texto puro** — ver seção 6.

### `eventos` — log de auditoria
`id`, `usuario`, `papel`, `acao`, `entidade`, `entidade_id`, `detalhe`, `created_at`.
Registra toda ação relevante (login, criar/editar/excluir, aprovar, importar, gerar pedido…).

---

## 5. Regras de negócio

### 5.1 Fluxo de status (situação)
Lista oficial (`constants.STATUS_LIST`):
`Solicitado → Cotação → Aprovação → Comprado → Concluído` (+ `Cancelado`).

Regras automáticas implementadas:
- **Aprovar um orçamento** (ou registrar aprovação) → a requisição vai para **"Aprovação"**
  (= *aprovado para compra*). **Não** vira "Comprado" ainda.
- **Gerar o Pedido de Compra (PDF)** → a requisição vira **"Comprado"**, preenchendo
  `data_compra` automaticamente (e o fornecedor a partir do orçamento aprovado, se vazio).
- Também existe **"Marcar como Comprado" manual** (sem precisar gerar o PDF).
- **Validações** (`app.validate_payload`): empresa, item e data_solicitação obrigatórios;
  valores não-negativos; data_compra ≥ data_solicitação; fornecedor obrigatório se
  Comprado/Concluído.

### 5.2 Aprovação **sem** orçamento
Como nem toda compra tem cotação, é possível **aprovar/reprovar a requisição direto pelo valor**,
gravando uma aprovação com `orcamento_id = NULL`. (Por isso `orcamento_id` é opcional.)

---

## 6. Autenticação, papéis e permissões (`auth.py` + `crud.py`)

### 6.1 Senhas
- Hash **PBKDF2-HMAC-SHA256, 100.000 iterações**, com **salt** aleatório de 16 bytes por usuário.
- Funções: `crud.hash_senha()`, `crud.verificar_senha()` (comparação por `secrets.compare_digest`).
- `crud.seed_admin()` cria um ADM inicial no primeiro acesso (login/senha via env `ADMIN_LOGIN`/`ADMIN_SENHA`, padrão `admin`/`admin`).

### 6.2 Mapa central de permissões
Toda autorização vive em **um único dicionário** (`auth.PERMISSOES`), fácil de ajustar:

| Ação \ Papel | ADM | GESTOR | COMPRADOR |
|---|:--:|:--:|:--:|
| editar | ✅ | ✅ | ✅ |
| excluir | ✅ | ❌ | ❌ |
| aprovar | ✅ | ✅ | ✅ |
| admin (painel) | ✅ | ❌ | ❌ |
| importar (Excel) | ✅ | ❌ | ❌ |
| ver_financeiro (dashboards) | ✅ | ✅ | ✅ |
| logs (aba Atividades) | ❌ | ❌ | ❌ |

`auth.pode("acao")` consulta esse mapa. As abas e botões da UI são exibidos conforme essas flags.
*(Hoje as permissões começam permissivas, propositalmente; o desenho permite apertar depois.)*

### 6.3 Sessão e login
`auth.require_login()` controla o gate de acesso (interrompe a página com a tela de login se não
autenticado). `auth.current_user()` e `auth.logout()` completam o ciclo.

---

## 7. Funcionalidades-chave e **como foram construídas**

### 7.1 Importação de PDF (o item mais relevante para integração) — `cotacao_pdf.py`
**O que faz:** recebe os bytes de um PDF gerado pela plataforma oficial e devolve um dicionário
pronto para virar requisição (com itens). Reconhece **dois tipos** automaticamente.

**Como chegamos:** analisamos PDFs reais (Cartas de Cotação 4057/4075 e Pedido de Compra 4048),
identificamos que o **PyMuPDF** (`page.find_tables()`) extrai a tabela de produtos de forma
confiável, inclusive **linhas de continuação** (descrição/códigos quebrados em 2 linhas). Os
metadados (nº, empresa, datas, fornecedor, total, parcelas) são extraídos do **texto** via regex.

Função pública: **`parse_documento(file_bytes) -> dict`**
- Detecta o tipo pelo texto: `"Pedido de Compra Nº"` → pedido; senão → cotação.
- Internamente: `_parse_cotacao()` / `_parse_pedido()`, apoiados por:
  - `_extrair_itens(page)` — lê a tabela, mescla continuações, captura código/desc/qtde/unidade
    e (no pedido) valor unitário/total.
  - `_parse_qtde("8,00 UN") → (8.0, "UN")`, `_parse_money("1.992,00") → 1992.0`,
    `_br_to_iso("17/06/2026") → "2026-06-17"`, `_empresa_curta()`, `_resumo_item()`.

**Saída — Carta de Cotação:** `tipo=cotacao`, `situacao=Solicitado`, sem preços; itens com
código/desc/qtde/unidade.
**Saída — Pedido de Compra:** `tipo=pedido`, `situacao=Comprado`, com **fornecedor, valor total,
desconto, parcelas e contato** (parcelas/contato vão para `observacao`); itens **com valor
unitário e total**; `data_compra` preenchida.

> **Para o TI:** este módulo é **independente de UI e de banco** — recebe bytes, devolve dict.
> Pode ser chamado de qualquer serviço. É o coração da automação "PDF → requisição".

### 7.2 Geração do Pedido de Compra em PDF — `pedido.py`
**`gerar_pedido_pdf(empresa_key, pedido) -> bytes`** (ReportLab). Monta cabeçalho com logo/dados
cadastrais da empresa emissora (perfis em `pedido.EMPRESAS`: ENGEMETAL/Bluesun e ENGECOMP),
destinatário, e **dois modos**:
- **Por itens** (tabela quant × valor unit × total) — padrão.
- **Serviço / valor fechado** (`tipo="servico"`) — bloco de descrição livre + valor único, para
  serviços/locação/frete onde não cabe item a item.
Faz subtotal/desconto/total e condições de pagamento. Logo é redimensionada preservando proporção.

### 7.3 Importação/Exportação Excel — `excel_io.py`
`load_excel()`, `normalize_dataframe()` (mapeia cabeçalhos via `constants.COLUMN_MAP`, normaliza
datas/decimais/NF), `dataframe_to_records()`, `export_to_excel()`. `filter_required_fields()`
descarta linhas sem empresa/item/data.

### 7.4 Métricas e análises — `metrics.py` (puro pandas)
`fetch_dataframe(filters)` carrega o recorte filtrado; sobre ele:
- KPIs: `total_gasto`, `valor_em_aberto`, `ticket_medio`, `tempo_medio_atendimento`.
- Distribuições: `contagem_por_situacao`, `evolucao_mensal`.
- Fornecedores: `top_fornecedores`, `pareto_fornecedores` (concentração 80% do gasto),
  `tempo_por_fornecedor`.
- Por dimensão: `metricas_por_empresa`, `metricas_por_projeto`, `distribuicao_tempo`.

### 7.5 Auditoria — `crud.registrar_evento()` / `crud.list_eventos()`
Toda ação relevante chama `registrar_evento(usuario, papel, acao, entidade, entidade_id, detalhe)`.
É **resiliente**: se a gravação do log falhar, **não derruba** a operação principal (só registra o
erro no log do servidor).

---

## 8. Acesso a dados — `crud.py` (resumo das funções)

**Requisições:** `fetch_requisicoes`, `count_requisicoes`, `get_by_id`, `create_requisicao`
(retorna o novo id via `RETURNING`), `update_requisicao`, `delete_requisicao`,
`set_valor_requisicao`, `fetch_distinct`, `fetch_counts`, `build_filters` (monta WHERE
parametrizado a partir dos filtros da UI).

**Itens:** `list_itens`, `replace_itens` (substitui em bloco), `fetch_itens_resumo`.

**Orçamentos:** `list_orcamentos`, `create_orcamento`, `update_orcamento`, `delete_orcamento`.

**Aprovações:** `list_aprovacoes`, `create_aprovacao`.

**Anexos:** `list_anexos`, `create_anexo`, `get_anexo_conteudo` (normaliza BLOB → `bytes`),
`delete_anexo`.

**Projetos:** `list_projetos`, `fetch_all_projetos`, `create_projeto`, `update_projeto`,
`delete_projeto`, `fetch_requisicoes_por_projeto`, `fetch_orcamentos_por_projeto`.

**Usuários/auditoria:** `list_usuarios`, `get_usuario_por_login`, `create_usuario`,
`update_usuario`, `set_senha`, `count_usuarios`, `seed_admin`, `registrar_evento`, `list_eventos`.

> Todas as queries usam **`text()` com parâmetros nomeados** (`:param`) — protegidas contra SQL
> injection. A única montagem dinâmica (`fetch_distinct`) recebe **nomes de coluna fixos do
> código**, nunca entrada do usuário.

---

## 9. Banco e migrações — `db.py`

- `get_database_url()` lê `DATABASE_URL` (Postgres em produção; SQLite local como fallback).
- `init_db()` cria as tabelas e roda **migrações leves** no padrão *"se a coluna/tabela não
  existe, faz `ALTER TABLE`"* — funciona tanto em SQLite quanto em Postgres.
- `insert_many()` para carga em lote (importação Excel).

> **Limitação conhecida:** as migrações são manuais (sem Alembic). Decisão consciente: para a
> escala atual funciona e evita risco; na plataforma da empresa, recomenda-se usar o **mecanismo
> de migração já existente** lá.

---

## 10. Telas (em `app.py`) — mapa funcional

- **Dashboard** — 5 KPIs (Total, Valor, Em Aberto, Ticket Médio, Tempo Médio) + gráficos por status/fornecedor.
- **Requisições** — lista (AgGrid) com **edição inline** (status, empresa, item, fornecedor, valor,
  datas, código original); criação manual (com itens); **importação de PDF**; e um **modal de
  detalhes** por requisição com abas: Dados, Itens, Orçamentos, Aprovações, Anexos, Pedido.
- **Análises** — 7 seções (evolução temporal, status, fornecedores/Pareto, empresa, projeto,
  prazos, tabela completa).
- **Projetos** — cadastro e consolidação por projeto.
- **Importar** (ADM) — carga via Excel.
- **Admin** (ADM) — gestão de usuários (criar/editar/ativar/resetar senha) e status da conexão.

---

## 11. Decisões de design (o "porquê")

1. **Lógica separada da UI** (`src/`) — justamente para permitir reaproveitamento/integração.
2. **Datas em ISO no banco, BR na tela** — ordenação correta sem perder o padrão brasileiro.
3. **Permissões num mapa central** — mudar autorização é alterar **uma linha**, não caçar `if`s.
4. **Auditoria que nunca quebra a operação** — log é importante, mas não pode travar uma compra.
5. **Aprovação opcional de orçamento** — reflete a realidade (nem toda compra cota).
6. **Status só vira "Comprado" ao emitir o pedido** — espelha o processo real de compras.
7. **Parsing de PDF baseado em PyMuPDF + regex** — robusto a linhas de continuação; calibrado em
   documentos reais e fácil de estender para novos layouts.

---

## 12. Limitações conhecidas & recomendações para a integração

- **Sem testes automatizados** — recomenda-se criar uma suíte (parsing de PDF, auth, fluxo de
  status, métricas) **antes/junto** da integração. É o maior ganho de segurança.
- **Migrações manuais** — usar o mecanismo da plataforma destino.
- **Validação só na aplicação** — ao integrar, vale adicionar constraints no banco (defesa em
  profundidade), com cuidado em dados existentes.
- **UI acoplada ao Streamlit** — a interface seria refeita no padrão da plataforma; o **núcleo
  (`src/`) é reaproveitável**.

### Roteiro sugerido de integração
1. **Portar o modelo de dados** (seção 4) para o schema da plataforma.
2. **Reaproveitar `cotacao_pdf.py`** (parsing) e `pedido.py` (geração) — são autocontidos.
3. **Traduzir as regras** de status/permissão (seções 5 e 6) para o backend da plataforma.
4. **Reescrever a UI** no padrão da plataforma, consumindo as mesmas regras.
5. **Adicionar testes** cobrindo parsing, status e permissões.

---

*Documento gerado a partir do código-fonte atual (branch de desenvolvimento). Para dúvidas sobre
qualquer função específica, todas estão referenciadas por arquivo na seção correspondente.*
