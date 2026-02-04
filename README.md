# Sistema de Controle de Requisições de Compras

Aplicação Streamlit simples para substituir planilhas de requisições de compras com importação/exportação de Excel, CRUD e métricas básicas.

## ✅ Requisitos atendidos
- PIN de acesso simples (`@Compras`).
- Importação inicial de Excel com normalização de cabeçalhos, datas e valores.
- CRUD completo (criar, editar, visualizar, filtrar).
- Métricas (total gasto, total por empresa e por fornecedor).
- Exportação para Excel com filtros aplicados.
- Banco SQLite local em `/data/app.db`.

## 📁 Estrutura do projeto
```
/app.py
/src/
  auth.py
  constants.py
  crud.py
  db.py
  excel_io.py
  metrics.py
/data/ (criada automaticamente em runtime)
/README.md
/requirements.txt
/.gitignore
```

## 🛠️ Como rodar localmente

### 1) Crie o ambiente virtual
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou
.venv\Scripts\activate     # Windows
```

### 2) Instale dependências
```bash
pip install -r requirements.txt
```

### 3) Execute o app
```bash
streamlit run app.py
```

Acesse o endereço indicado no terminal.

## 🔐 PIN de acesso
- PIN fixo: `@Compras`
- Após autenticação, o acesso permanece válido na `session_state`.

## 📤 Importação de Excel
- Acesse a aba **Importar**.
- Faça upload do `.xlsx` e escolha a aba da planilha (ou use a primeira).
- O sistema normaliza cabeçalhos, datas e valores automaticamente.
- Linhas totalmente vazias são ignoradas.
- Duplicatas **não** são removidas automaticamente (aviso exibido).

## 🧾 Estrutura esperada do Excel
Colunas (com variações aceitas em maiúsculas/minúsculas e acentos):
```
Empresa, Setor, Requisição, Data Solicitação, Data Compra, Fornecedor,
Qtde, Item, Entrega, Situação, Valor, Valor Desconto, NF, Observação
```

### Normalizações aplicadas
- Datas: aceita `dd/mm/aaaa` ou datetime e salva como `YYYY-MM-DD`.
- Valores: aceita `1.234,56`, `1234,56` ou `1234.56`.
- NF: convertida para texto para manter zeros à esquerda.
- Coluna A ou linha 1 vazia são tratadas automaticamente.

## 🧩 CRUD e filtros
A aba **Requisições** permite:
- Criar novos registros.
- Editar registros existentes.
- Filtrar por empresa, setor, fornecedor, situação, períodos e busca textual.

### Validações
- Empresa, Item e Data Solicitação são obrigatórios.
- Qtde deve ser inteiro >= 0.
- Situação aceita: `Solicitado`, `Comprado`, `Entregue`, `Cancelado`.

## 📊 Métricas (Dashboard)
As métricas respeitam os filtros da sidebar:
- Total gasto (valor - desconto)
- Total por empresa
- Total por fornecedor

## 📥 Exportação
- Disponível na aba **Dashboard** e **Requisições**.
- Exporta apenas os registros filtrados.
- O arquivo é baixado direto no navegador.

---

## ✅ Passo a passo manual (guia rápido)
1. Crie o ambiente virtual e instale dependências.
2. Execute `streamlit run app.py`.
3. Digite o PIN `@Compras`.
4. Vá na aba **Importar** e carregue a planilha inicial.
5. Use a aba **Requisições** para editar ou criar novos registros.
6. Use os filtros na sidebar para segmentar dados.
7. Vá em **Dashboard** para métricas e exportações.
