# Sistema de Controle de Requisições de Compras

Aplicação web em **Streamlit** para gerenciar requisições de compra de ponta a ponta — substitui planilhas soltas por um sistema com cadastro, cotação, aprovação, anexos, controle de projetos e dashboards executivos.

O app roda 100% no navegador, com banco de dados (Postgres em produção / SQLite local) e está publicado no Railway.

---

## Sumário

- [O que o app faz](#o-que-o-app-faz)
- [Estrutura das telas (abas)](#estrutura-das-telas-abas)
- [Guia de uso passo a passo](#guia-de-uso-passo-a-passo)
- [Conceitos importantes](#conceitos-importantes)
- [Rodar localmente](#rodar-localmente)
- [Deploy (Railway)](#deploy-railway)
- [Arquitetura do código](#arquitetura-do-código)
- [FAQ / Solução de problemas](#faq--solução-de-problemas)

---

## O que o app faz

É um sistema completo de **controle de compras** organizado em torno da "Requisição" (o pedido de compra). Para cada requisição você consegue:

- **Cadastrar e editar** todos os dados (empresa, setor, projeto, item, fornecedor, valores, datas, NF, observação).
- **Anexar múltiplos orçamentos** de fornecedores diferentes e comparar.
- **Registrar aprovações** (workflow: aprovado, reprovado, devolvido, comentário).
- **Subir arquivos** (orçamento em PDF, nota fiscal, contrato etc.) e baixá-los depois.
- **Acompanhar o status** ao longo do fluxo: `Solicitado → Cotação → Aprovação → Comprado → Concluído` (ou `Cancelado`).
- **Agrupar por projeto** e ver o gasto consolidado de cada um.
- **Analisar** tudo em dashboards com KPIs, gráficos, curva de Pareto de fornecedores, tempo médio de atendimento, saving etc.
- **Importar** uma planilha Excel existente e **exportar** os dados filtrados de volta para Excel.

---

## Estrutura das telas (abas)

A interface tem uma **sidebar de filtros** (vale para todas as abas) e **5 abas** principais.

### Sidebar — Filtros (sempre visível)
- **Visualização rápida**: presets com contadores — `Todos`, `Pendentes` (Solicitado), `Comprados`, `Concluídos`.
- **Busca global**: campo de texto que procura por item, fornecedor, nº de requisição etc.
- **Período rápido**: botões `Hoje`, `Esta semana`, `Este mês`, `Último mês`.
- **Filtros avançados**: Empresa, Setor, Projeto, Fornecedor, Situação e faixas de Data Solicitação / Data Compra.
- **Limpar Filtros**: zera tudo.
- **Admin (MVP)**: ação destrutiva para limpar a base inteira (exige marcar confirmação e digitar `LIMPAR TUDO`). Use só em homologação.

### 1. 📊 Dashboard
Visão executiva dos dados **já filtrados**:
- **KPIs**: Total de Requisições, Valor Total, Em Aberto, Ticket Médio, Tempo Médio (dias) e Saving (% de desconto).
- **Situação das requisições**: contagem e valor por status.
- **Gráficos**: Valor por Status e Top 10 Fornecedores por Valor.
- **Tabelas resumo**: Total por Empresa e Total por Fornecedor.
- **Exportar Excel** dos dados filtrados.

### 2. 📋 Requisições
O coração operacional do sistema:
- **Criar Nova Requisição** (formulário em expander).
- **Tabela interativa** (AgGrid) com cores por status, ordenação, filtro por coluna e paginação.
- **Edição de status inline**: dá pra trocar o status direto na célula da coluna "Status".
- **Botão 📝** em cada linha abre o **modal de detalhes** com 4 abas:
  - **📝 Editar Dados** — editar/excluir a requisição.
  - **💰 Orçamentos** — adicionar, listar e excluir orçamentos.
  - **✅ Aprovações** — registrar ações; aprovar muda o status para `Comprado` automaticamente.
  - **📁 Anexos** — subir, baixar e excluir arquivos.
- Opção **Ocultar Concluídos e Cancelados** e **Exportar Excel**.

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
- Ao selecionar um projeto: métricas (nº requisições, nº orçamentos, total gasto), breakdown de status, tabela de requisições e orçamentos consolidados do projeto.

### 5. 📥 Importar
- Upload de arquivo **.xlsx**, escolha da planilha (aba) e importação.
- Os cabeçalhos são normalizados automaticamente (ver [COLUMN_MAP](#mapeamento-de-colunas-na-importação)).
- Linhas sem **Empresa, Item ou Data Solicitação** (campos obrigatórios) são ignoradas.
- ⚠️ A importação **não** remove duplicatas automaticamente.

---

## Guia de uso passo a passo

### Criar uma requisição do zero
1. Vá na aba **📋 Requisições** → **➕ Criar Nova Requisição**.
2. Preencha os obrigatórios (marcados com `*`): **Empresa**, **Item**, **Data Solicitação**.
3. Empresa, Setor e Projeto podem ser escolhidos da lista existente ou criados na hora com **"+ Nova/Novo..."**.
4. Clique em **Criar requisição**.

### Fazer cotação e aprovar
1. Na tabela, clique no **📝** da linha desejada.
2. Aba **💰 Orçamentos** → preencha fornecedor/valor/prazo → **Adicionar orçamento** (repita para comparar).
3. Aba **✅ Aprovações** → escolha a ação (ex: `APROVADO`) → **Registrar ação**.
   - Ao aprovar, o status da requisição vira **Comprado** automaticamente.
4. Aba **📁 Anexos** → suba o orçamento/NF/contrato e classifique o tipo.

### Mudar status rapidamente
- Na tabela de Requisições, clique duas vezes na célula da coluna **Status** e escolha o novo valor — salva sozinho.

### Acompanhar um projeto
1. Aba **📁 Projetos** → selecione o projeto na lista à esquerda.
2. Veja métricas, status e as requisições/orçamentos vinculados à direita.

### Importar planilha legada
1. Aba **📥 Importar** → selecione o `.xlsx` → escolha a aba → **📥 Importar**.
2. Confira a mensagem de quantos registros entraram e quantos foram ignorados.

### Exportar
- Em **Dashboard** ou **Requisições**, clique em **📄 Exportar Excel** → **⬇️ Baixar arquivo**. Respeita os filtros ativos.

---

## Conceitos importantes

### Status (situação) das requisições
`Solicitado` · `Cotação` · `Aprovação` · `Comprado` · `Concluído` · `Cancelado`

Na tabela cada status tem uma cor própria para leitura rápida.

### Campos da requisição
Empresa, Setor, Projeto, Nº Requisição, Data Solicitação, Data Compra, Fornecedor, Qtde, Item, Entrega, Situação, Valor, Valor Desconto, NF, Observação.

### Mapeamento de colunas na importação
A importação aceita variações de cabeçalho (definidas em `src/constants.py → COLUMN_MAP`), por exemplo: `req → requisicao`, `quantidade → qtde`, `nota_fiscal → nf`, `observacoes → observacao`, `datacompra → data_compra` etc. Cabeçalhos são normalizados (minúsculas, sem acento) antes de mapear.

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

### Variáveis de ambiente
| Variável | Para quê |
|---|---|
| `DATABASE_URL` | **Obrigatória em produção.** String do Postgres do Railway. Sem ela, o app para e avisa que o banco não é persistente. |
| `MISE_PYTHON_GITHUB_ATTESTATIONS` | Defina como `false` se o build falhar na instalação do Python (ver FAQ). |

> **Persistência:** em produção sempre aponte `DATABASE_URL` para o Postgres do Railway. O SQLite reseta a cada reinício do container.

---

## Arquitetura do código

```
app.py                # toda a UI Streamlit (abas, formulários, tabela, modais)
Procfile              # comando de start (streamlit)
requirements.txt      # dependências
.python-version       # versão do Python (3.12.3) para o Railpack
mise.toml             # config do mise no build (desliga attestations do Python)
.streamlit/           # config do servidor Streamlit (headless etc.)
src/
  ├── constants.py    # status, mapeamento e ordem de colunas, PIN
  ├── db.py           # conexão (Postgres/SQLite), init de tabelas, insert em massa
  ├── crud.py         # CRUD de requisições, orçamentos, aprovações, anexos, projetos
  ├── metrics.py      # agregações e indicadores para Dashboard/Análises
  ├── excel_io.py     # importar/exportar e normalizar Excel
  └── auth.py         # require_pin() — controle de acesso por PIN
```

**Stack:** Streamlit · pandas · SQLAlchemy (Postgres via psycopg2 / SQLite) · streamlit-aggrid · Plotly · openpyxl.

---

## FAQ / Solução de problemas

**O build no Railway falha com `No GitHub artifact attestations found for python@3.12.3`.**
É a verificação de assinatura do `mise` (não é o seu código). Já existe um `mise.toml` no repo desligando isso. Se ainda falhar, adicione a variável `MISE_PYTHON_GITHUB_ATTESTATIONS=false` em **Variables** do serviço no Railway e refaça o deploy.

**O app reclama que o banco "não é persistente" / "DATABASE_URL não configurada".**
Configure a variável `DATABASE_URL` apontando para o Postgres do Railway. Sem ela, em produção o app para de propósito para você não perder dados.

**Importei e apareceram registros duplicados.**
A importação não deduplica. Limpe duplicatas manualmente ou use a base limpa antes de importar.

**Linhas da planilha não foram importadas.**
Provavelmente faltou **Empresa**, **Item** ou **Data Solicitação** (campos obrigatórios). O app mostra quantas linhas foram ignoradas.
