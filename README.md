# Sistema de Controle de Requisições de Compras

Aplicação web em Streamlit para gerenciamento completo de requisições de compra, substituindo planilhas com CRUD, orçamentos, aprovações, anexos e métricas executivas.

---

## Funcionalidades

### Requisições
- CRUD completo com filtros avançados e paginação
- Campos: Empresa, Setor, Projeto, Nº Requisição, Datas, Fornecedor, Item, Qtde, Situação, Valor, Desconto, NF, Observação
- Situações disponíveis: `Solicitado`, `Comprado`, `Entregue`, `Cancelado`
- Criação inline de empresa, setor e projeto diretamente no formulário
- Padrão **master-detail**: tabela no corpo + painel de detalhe na sidebar

### Orçamentos
- Múltiplos orçamentos por requisição (fornecedor, valor, prazo, condições, status)

### Aprovações
- Workflow de aprovação com ações: `APROVADO`, `REPROVADO`, `DEVOLVIDO`, `COMENTÁRIO`
- Histórico completo de ações por requisição

### Anexos
- Upload de arquivos por requisição (tipos: orçamento, NF, contrato, outros)
- Armazenados no próprio banco como BLOB
- Download direto pelo app

### Projetos
- Tabela dedicada de projetos (nome único, descrição, data de criação)
- Criar, editar, excluir projetos
- Visão consolidada por projeto: métricas (nº requisições, nº orçamentos, total gasto), breakdown de status, listagem de requisições e orçamentos vinculados
- Ao criar/editar uma requisição com um projeto novo, ele é registrado automaticamente

### Dashboard
- KPIs: total gasto, total em aberto, quantidade de pendentes, ticket médio, tempo médio de atendimento
- Gráficos (Plotly): evolução mensal, total por empresa, top fornecedores, Pareto, distribuição por situação

### Análises
- Totais por empresa, fornecedor, projeto e situação
- Distribuição de tempos de atendimento
- Gráfico de evolução mensal

### Importação / Exportação
- Importar `.xlsx` com normalização automática de cabeçalhos, datas e valores
- Exportar registros filtrados para `.xlsx`

### Autenticação
- Acesso protegido por PIN (configurado em `src/constants.py`)

---

## Estrutura do projeto

```
COMPRAS/
├── app.py                  # Entrada do app Streamlit (UI + lógica de telas)
├── requirements.txt        # Dependências Python
├── Procfile                # Comando de inicialização (Railway/Heroku)
├── .python-version         # Versão fixada: 3.12.3
├── .streamlit/
│   └── config.toml         # Configurações do servidor Streamlit
└── src/
    ├── __init__.py
    ├── auth.py             # Autenticação por PIN
    ├── constants.py        # Constantes (PIN, colunas, status)
    ├── crud.py             # Todas as operações de banco de dados
    ├── db.py               # Definição das tabelas e init_db()
    ├── excel_io.py         # Importação e exportação de Excel
    └── metrics.py          # Funções de métricas e análises
```

---

## Banco de dados

Por padrão usa **SQLite** em `/data/app.db`. Em produção usa **PostgreSQL** quando `DATABASE_URL` estiver configurado.

### Tabelas

| Tabela | Descrição |
|---|---|
| `requisicoes` | Tabela principal com todos os dados da requisição |
| `orcamentos` | Orçamentos vinculados a requisições |
| `anexos` | Arquivos (BLOB) vinculados a requisições ou orçamentos |
| `aprovacoes` | Histórico de ações de aprovação |
| `projetos` | Cadastro de projetos (nome único, descrição) |

`init_db()` cria todas as tabelas automaticamente no primeiro acesso e executa migrações necessárias.

---

## Como rodar localmente

### 1. Pré-requisito
Python 3.10 ou superior instalado. No Windows, marque **"Add Python to PATH"** durante a instalação.

### 2. Crie e ative o ambiente virtual
```bash
python -m venv .venv

# Linux/Mac
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 3. Instale as dependências
```bash
pip install -r requirements.txt
```

### 4. Execute o app
```bash
streamlit run app.py
```

Acesse `http://localhost:8501` no navegador.

---

## Deploy no Railway (app + PostgreSQL)

### 1. Crie o banco PostgreSQL no Railway
1. Acesse [railway.app](https://railway.app) e crie uma conta.
2. Crie um novo projeto e adicione um serviço **PostgreSQL**.
3. Copie a variável `DATABASE_URL` gerada.

### 2. Suba o app no Railway via GitHub
1. Suba este repositório para o GitHub.
2. No Railway, crie um serviço **Web** apontando para o repositório.
3. O Railway usa o `Procfile` para iniciar: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
4. A versão do Python está fixada em `3.12.3` via `.python-version`.

### 3. Configure a variável de ambiente
No serviço Web do Railway, adicione:
```
DATABASE_URL=<URL do Postgres copiada no passo 1>
```

### 4. Acesse pela URL pública
O Railway gera uma URL pública. O app se conecta automaticamente ao Postgres e os dados são persistentes.

> **Atenção:** sem `DATABASE_URL`, o app usa SQLite local — que pode ser resetado a cada reinício em ambientes de deploy.

---

## Importação de Excel

A aba **Importar** aceita arquivos `.xlsx`. O sistema normaliza automaticamente:

| Campo | Normalização |
|---|---|
| Cabeçalhos | Aceita variações de maiúsculas/minúsculas e acentos |
| Datas | `dd/mm/aaaa` ou datetime → salvo como `YYYY-MM-DD` |
| Valores | `1.234,56`, `1234,56` ou `1234.56` → float |
| NF | Convertida para texto (preserva zeros à esquerda) |

Colunas esperadas (com variações aceitas):
```
Empresa, Setor, Projeto, Requisição, Data Solicitação, Data Compra,
Fornecedor, Qtde, Item, Entrega, Situação, Valor, Valor Desconto, NF, Observação
```

> Linhas com Empresa, Item ou Data Solicitação em branco são ignoradas. Duplicatas **não** são removidas automaticamente.

---

## Dependências

```
streamlit>=1.34.0
pandas==2.2.1
openpyxl==3.1.2
numpy==1.26.4
SQLAlchemy==2.0.27
psycopg2-binary==2.9.9
streamlit-aggrid==1.0.5
plotly>=5.18.0
```

---

## Admin (MVP)

Na sidebar, o expander **Admin (MVP)** contém o botão **Limpar base inteira**, que apaga todos os dados (requisições, orçamentos, anexos, aprovações e projetos) com dupla confirmação.
