# Sistema de Controle de Requisições de Compras

Aplicação web em **Streamlit** para gerenciar requisições de compra de ponta a ponta — substitui planilhas soltas por um sistema com cadastro, itens estruturados, cotação, aprovação por orçamento, anexos, controle de projetos, dashboards executivos e **geração de Pedido de Compra em PDF**.

O app roda 100% no navegador, com banco de dados (Postgres em produção / SQLite local) e está publicado no Railway.

---

## Sumário

- [O que o app faz](#o-que-o-app-faz)
- [Estrutura das telas (abas)](#estrutura-das-telas-abas)
- [O modal da requisição](#o-modal-da-requisição)
- [Gerador de Pedido de Compra (PDF)](#gerador-de-pedido-de-compra-pdf)
- [Guia de uso passo a passo](#guia-de-uso-passo-a-passo)
- [Conceitos importantes](#conceitos-importantes)
- [Rodar localmente](#rodar-localmente)
- [Deploy (Railway)](#deploy-railway)
- [Arquitetura do código](#arquitetura-do-código)
- [Modelo de dados](#modelo-de-dados)
- [FAQ / Solução de problemas](#faq--solução-de-problemas)

---

## O que o app faz

É um sistema completo de **controle de compras** organizado em torno da "Requisição" (o pedido interno de compra). Para cada requisição você consegue:

- **Cadastrar e editar** todos os dados (empresa, setor, projeto, item, fornecedor, valores, datas, NF, observação).
- **Detalhar itens estruturados** (descrição, quantidade, unidade, valor unitário) — o total é calculado automaticamente.
- **Anexar múltiplos orçamentos** de fornecedores diferentes e **aprovar/rejeitar cada um** (inclusive aprovação parcial).
- **Registrar aprovações por orçamento**, com detalhamento livre.
- **Subir arquivos** (orçamento em PDF, nota fiscal, contrato etc.), **vinculá-los a um orçamento** e baixá-los depois.
- **Acompanhar o status** ao longo do fluxo: `Solicitado → Cotação → Aprovação → Comprado → Concluído` (ou `Cancelado`).
- **Gerar o Pedido de Compra em PDF** (Engemetal/Bluesun ou Engecomp) pronto para enviar ao fornecedor.
- **Agrupar por projeto** e ver o gasto consolidado de cada um.
- **Analisar** tudo em dashboards com KPIs, gráficos, curva de Pareto de fornecedores, tempo médio de atendimento, saving etc.
- **Importar** uma planilha Excel existente e **exportar** os dados filtrados de volta para Excel.

Cada requisição registra **auditoria** (criada em / última alteração) e as exclusões pedem **confirmação** e removem os dados filhos em **cascata**.

---

## Estrutura das telas (abas)

A interface tem uma **sidebar de filtros** (vale para todas as abas) e **5 abas** principais.

### Sidebar — Filtros (sempre visível)
- **Visualização rápida**: presets com contadores — `Todos`, `Pendentes` (Solicitado), `Comprados`, `Concluídos`.
- **Busca global**: campo de texto que procura por item, fornecedor, nº de requisição etc.
- **Período rápido**: botões `Hoje`, `Esta semana`, `Este mês`, `Último mês`.
- **Filtros avançados**: Empresa, Setor, Projeto, Fornecedor, Situação e faixas de Data Solicitação / Data Compra.
- **Limpar Filtros**: zera tudo.
- **Admin (MVP)**: ação destrutiva para limpar a base inteira (exige confirmação). Use só em homologação.

### 1. 📊 Dashboard
Visão executiva dos dados **já filtrados**:
- **KPIs**: Total de Requisições, Valor Total, Em Aberto, Ticket Médio, Tempo Médio (dias) e Saving (% de desconto).
- **Situação das requisições**: contagem e valor por status.
- **Gráficos**: Valor por Status e Top 10 Fornecedores por Valor.
- **Tabelas resumo**: Total por Empresa e Total por Fornecedor.
- **Exportar Excel** dos dados filtrados.

> O Dashboard é só painel/relatório. As ações (criar requisição, gerar pedido etc.) ficam na aba **📋 Requisições**.

### 2. 📋 Requisições
O coração operacional do sistema:
- **Criar Nova Requisição** (formulário em expander; o campo "+ Nova empresa/setor/projeto" aparece só quando você escolhe criar).
- **Ordenar por** (Data Solicitação, Requisição, Empresa, Item, Fornecedor, Valor, Status) + **sentido** (crescente/decrescente) — vale para **todas as páginas**.
- **Tabela interativa** (AgGrid) com cores por status, paginação e:
  - Coluna **Requisição** (`REQ-0001`) **clicável** → abre o [modal de detalhes](#o-modal-da-requisição).
  - Badges **💰 Orç.** e **📎 Anexos** por linha, **clicáveis** → abrem o modal direto na aba correspondente.
  - **Edição inline com um clique**: edite **Status, Empresa, Item, Fornecedor e Valor** direto na célula — salva ao sair dela.
  - Datas exibidas em **DD/MM/AAAA** (ordenação correta internamente).
- Opção **Ocultar Concluídos e Cancelados** e **📄 Exportar Excel** (respeita os filtros).

### 3. 📈 Análises
Relatórios analíticos mais profundos (sobre os dados filtrados):
- Evolução temporal (requisições por mês e valor comprado por mês).
- Distribuição por status (pizza + barras de valor).
- Análise de fornecedores: Top 15 + **Curva de Pareto** (quantos fornecedores concentram 80% do gasto).
- Análise por Empresa e por Projeto.
- Indicadores de prazo: histograma do tempo de atendimento e tempo médio por fornecedor.
- Tabela completa expansível.

### 4. 📁 Projetos
Gestão de projetos e consolidação de gastos:
- Criar / editar / excluir projeto (excluir apenas desvincula as requisições, não as apaga).
- Ao selecionar um projeto: métricas (nº requisições, nº orçamentos, total gasto), breakdown de status, tabela de requisições e orçamentos consolidados.

### 5. 📥 Importar
- Upload de arquivo **.xlsx**, escolha da planilha (aba) e importação.
- Os cabeçalhos são normalizados automaticamente (ver [Mapeamento de colunas](#mapeamento-de-colunas-na-importação)).
- Datas são convertidas para formato ISO; linhas sem **Empresa, Item ou Data Solicitação** são ignoradas.
- ⚠️ A importação **não** remove duplicatas automaticamente.

---

## O modal da requisição

Clique no código **REQ-0001** (ou numa badge 💰/📎) para abrir o modal, que tem **6 abas**:

| Aba | O que faz |
|---|---|
| **📝 Editar Dados** | Edita todos os campos da requisição. Mostra a auditoria (criada em / última alteração). Excluir exige **confirmação** e remove itens/orçamentos/anexos/aprovações em **cascata**. |
| **📦 Itens** | Planilha editável de itens estruturados (descrição, qtde, unidade, valor unit., obs). Mostra o **total previsto** e pode **atualizar o Valor da requisição** com a soma dos itens. |
| **💰 Orçamentos** | Lista os orçamentos com status (✅/🟡/❌) e botões **✅ aprovar / ❌ rejeitar** por linha. Adicionar e excluir (com confirmação). |
| **✅ Aprovações** | Registra aprovação **por orçamento específico**: `APROVADO`, `APROVADO PARCIAL`, `REPROVADO` ou `COMENTÁRIO`, com campo de detalhamento. Atualiza o status do orçamento e da requisição. |
| **📁 Anexos** | Sobe, lista, baixa e exclui arquivos. Cada anexo pode ser **vinculado a um orçamento**. |
| **🧾 Pedido** | [Gera o Pedido de Compra em PDF](#gerador-de-pedido-de-compra-pdf). |

---

## Gerador de Pedido de Compra (PDF)

Disponível na aba **🧾 Pedido** dentro de cada requisição. Reaproveita as **logos e os dados cadastrais** das empresas (extraídos dos modelos oficiais) num layout próprio e mais limpo.

**Como funciona:**
1. Escolha a **empresa emissora**: **Engemetal** (logo Bluesun, verde) ou **Engecomp** (azul).
2. Defina **número** e **data** do pedido.
3. Preencha o **destinatário (fornecedor)** — o nome já vem do campo Fornecedor; o resto (A/C, CNPJ, e-mail, endereço, cidade, CEP) você completa.
4. Os **itens** vêm pré-preenchidos pelos itens estruturados (ou pelo item principal) e são editáveis numa planilha (Quant., Descrição, Valor Unit., Prazo).
5. Ajuste **Desconto**, **Pagamento** (pré-preenchido pelo orçamento aprovado, se houver), **Entrega** e **Observações**.
6. Clique em **🧾 Gerar PDF do pedido** → **⬇️ Baixar pedido (PDF)**.

> O que você edita nessa aba serve **só para montar o PDF** — não altera os dados salvos da requisição.

As empresas emissoras (razão social, CNPJ/IE, contatos, e-mail de NF, cor e logo) ficam em `src/pedido.py → EMPRESAS`. As logos estão em `assets/`.

---

## Guia de uso passo a passo

### Criar uma requisição do zero
1. Aba **📋 Requisições** → **➕ Criar Nova Requisição**.
2. Preencha os obrigatórios (`*`): **Empresa**, **Item**, **Data Solicitação**.
3. Empresa, Setor e Projeto podem ser escolhidos da lista ou criados na hora com **"+ Nova/Novo..."**.
4. Clique em **Criar requisição**.

### Detalhar itens, cotar e aprovar
1. Na tabela, clique no código **REQ-XXXX**.
2. Aba **📦 Itens** → preencha a planilha de itens → **Salvar itens**.
3. Aba **💰 Orçamentos** → adicione os orçamentos dos fornecedores → use **✅/❌** para aprovar/rejeitar.
4. Aba **✅ Aprovações** → escolha o **orçamento** e a **decisão** (inclui *parcial*) → **Registrar aprovação**.
5. Aba **📁 Anexos** → suba o orçamento/NF/contrato (opcionalmente vinculado a um orçamento).
6. Aba **🧾 Pedido** → gere o PDF para o fornecedor.

### Mudar status / editar rapidamente
- Na tabela, clique numa célula de **Status, Empresa, Item, Fornecedor ou Valor** e edite — salva ao sair da célula.

### Acompanhar um projeto
- Aba **📁 Projetos** → selecione o projeto → veja métricas, status e itens vinculados.

### Importar / Exportar
- **Importar**: aba **📥 Importar** → `.xlsx` → escolha a aba → **Importar**.
- **Exportar**: em **Dashboard** ou **Requisições** → **📄 Exportar Excel** (respeita os filtros).

---

## Conceitos importantes

### Status (situação) das requisições
`Solicitado` · `Cotação` · `Aprovação` · `Comprado` · `Concluído` · `Cancelado`
Cada status tem uma cor própria na tabela para leitura rápida.

### Validações
Ao salvar uma requisição o app verifica: Empresa/Item/Data Solicitação obrigatórios, valores **não negativos**, **Data Compra ≥ Data Solicitação** e **Fornecedor obrigatório** quando a situação é `Comprado`/`Concluído`.

### Padrão monetário
Valores são exibidos no padrão brasileiro **R$ 1.234,56**.

### Auditoria e exclusões
Toda requisição guarda `created_at`/`updated_at`. Excluir requisição, orçamento ou anexo pede **confirmação**; a exclusão de requisição remove os dados filhos em **cascata**.

### Mapeamento de colunas na importação
A importação aceita variações de cabeçalho (em `src/constants.py → COLUMN_MAP`): `req → requisicao`, `quantidade → qtde`, `nota_fiscal → nf`, `observacoes → observacao`, `datacompra → data_compra` etc. Cabeçalhos são normalizados (minúsculas, sem acento) antes de mapear.

### Normalização de texto
Empresa, setor e projeto são salvos em **MAIÚSCULAS** para evitar duplicatas por diferença de caixa.

---

## Rodar localmente

```bash
# 1. (opcional) criar venv
python -m venv .venv && source .venv/bin/activate

# 2. instalar dependências
pip install -r requirements.txt

# 3. rodar
streamlit run app.py
```

Sem `DATABASE_URL` configurada, o app usa **SQLite local** (arquivo) — bom para testar, mas não persiste em deploy.

---

## Deploy (Railway)

O deploy usa o **Railpack**, que detecta Python via `.python-version`, instala as deps de `requirements.txt` e sobe o comando do `Procfile`:

```
web: streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

> ⚠️ Ao adicionar dependências novas (como a `reportlab` do gerador de PDF), é preciso **refazer o deploy** para que o Railway as instale.

### Variáveis de ambiente
| Variável | Para quê |
|---|---|
| `DATABASE_URL` | **Obrigatória em produção.** String do Postgres do Railway. Sem ela, o app para e avisa que o banco não é persistente. |
| `MISE_PYTHON_GITHUB_ATTESTATIONS` | Defina como `false` se o build falhar na instalação do Python (ver FAQ). |

> **Persistência:** em produção sempre aponte `DATABASE_URL` para o Postgres do Railway. O SQLite reseta a cada reinício do container.

---

## Arquitetura do código

```
app.py                # toda a UI Streamlit (abas, formulários, tabela, modais, gerador)
Procfile              # comando de start (streamlit)
requirements.txt      # dependências
.python-version       # versão do Python para o Railpack
mise.toml             # config do mise no build (desliga attestations do Python)
.streamlit/           # config do servidor Streamlit (headless etc.)
assets/               # logos das empresas usadas no PDF (logo_bluesun.png, logo_engecomp.png)
src/
  ├── constants.py    # status, mapeamento e ordem de colunas, PIN
  ├── db.py           # conexão (Postgres/SQLite), schema, migrações, insert em massa
  ├── crud.py         # CRUD de requisições, itens, orçamentos, aprovações, anexos, projetos
  ├── metrics.py      # agregações e indicadores para Dashboard/Análises
  ├── excel_io.py     # importar/exportar e normalizar Excel
  ├── pedido.py       # gerador de Pedido de Compra em PDF (reportlab)
  └── auth.py         # require_pin() — controle de acesso por PIN
```

**Stack:** Streamlit · pandas · SQLAlchemy (Postgres via psycopg2 / SQLite) · streamlit-aggrid · Plotly · openpyxl · reportlab.

---

## Modelo de dados

| Tabela | Conteúdo |
|---|---|
| `requisicoes` | Dados principais da requisição + `created_at`/`updated_at`. |
| `itens` | Itens estruturados de cada requisição (descrição, qtde, unidade, valor unit.). |
| `orcamentos` | Orçamentos por requisição (fornecedor, valor, prazo, condições, status). |
| `aprovacoes` | Histórico de aprovações, vinculado a um `orcamento_id`. |
| `anexos` | Arquivos (BLOB), com vínculo opcional a um `orcamento_id`. |
| `projetos` | Catálogo de projetos. |

O schema é criado/migrado automaticamente em `db.py → init_db()` na inicialização do app (inclui as migrações de `projeto`, auditoria, `orcamento_id` em aprovações e a tabela `itens`).

---

## FAQ / Solução de problemas

**A aba 🧾 Pedido dá erro de import (`reportlab`).**
A dependência foi adicionada ao `requirements.txt`. **Refaça o deploy** no Railway para instalá-la.

**A edição com um clique na tabela não abre o editor.**
Só são editáveis as colunas **Status, Empresa, Item, Fornecedor e Valor**. Em algumas versões do componente o **duplo clique** também funciona como alternativa.

**O build no Railway falha com `No GitHub artifact attestations found for python`.**
É a verificação de assinatura do `mise`. Já existe um `mise.toml` desligando isso. Se persistir, adicione `MISE_PYTHON_GITHUB_ATTESTATIONS=false` em **Variables** e refaça o deploy.

**O app reclama que o banco "não é persistente" / "DATABASE_URL não configurada".**
Configure a variável `DATABASE_URL` apontando para o Postgres do Railway. Sem ela, em produção o app para de propósito para você não perder dados.

**Importei e apareceram registros duplicados.**
A importação não deduplica. Limpe duplicatas manualmente ou use a base limpa antes de importar.

**Linhas da planilha não foram importadas.**
Provavelmente faltou **Empresa**, **Item** ou **Data Solicitação** (obrigatórios). O app mostra quantas linhas foram ignoradas.
