# Sistema de Controle de Requisições de Compras

Aplicação Streamlit simples para substituir planilhas de requisições de compras com importação/exportação de Excel, CRUD e métricas básicas.

## ✅ Requisitos atendidos
- Sem autenticação nesta fase de MVP (acesso direto temporário).
- Importação inicial de Excel com normalização de cabeçalhos, datas e valores.
- CRUD completo (criar, editar, visualizar, filtrar).
- Requisições agrupadas por **Projeto**, com visão consolidada de itens e orçamentos por projeto.
- Métricas (total gasto, total por empresa e por fornecedor).
- Exportação para Excel com filtros aplicados.
- Banco local por padrão (SQLite) e **Postgres via Railway** quando `DATABASE_URL` estiver configurado.

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

## 🔓 Acesso
- Nesta fase de MVP, o app está sem senha/login para agilizar validações.
- Em etapa posterior será implementado controle de usuários e autenticação.

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

## ✅ Fluxo de UX atualizado (edição rápida + gestão detalhada)
- A aba **Requisições** começa com **➕ Criar Nova Requisição** em expander no topo, seguido da grade de edição rápida (inline).
- O Dashboard traz KPIs executivos: total gasto, total em aberto, quantidade de pendentes e percentual de economia.
- No formulário de requisição, é possível **selecionar projeto existente** ou **criar novo projeto** na hora.
- Campos de **Empresa** e **Setor** usam seleção de valores existentes com opção de novo cadastro, reduzindo erros de digitação.
- A visualização principal segue padrão **master-detail**: tabela no corpo principal e detalhe da requisição na **sidebar**.
- A sidebar usa abas (**📝 Dados**, **✅ Aprovação**, **📁 Arquivos**) para editar dados, aprovar, gerenciar orçamentos e anexos sem poluir o corpo da tela.
- A aba **Projetos** consolida as requisições e orçamentos de cada projeto para gestão macro.
- Inclui opção de foco rápido em pendentes (`Solicitado`) sem abrir uma aba separada.

> Observação: os anexos ficam salvos no próprio banco (BLOB). Para manter boa performance no MVP, use arquivos pequenos/médios e evite anexos muito grandes.

- No menu lateral, em **Admin (MVP)**, existe o botão **Limpar base inteira** para zerar dados (requisições, orçamentos, anexos e aprovações) com dupla confirmação.

---

## ✅ Passo a passo manual (guia rápido)
1. Crie o ambiente virtual e instale dependências.
2. Execute `streamlit run app.py`.
3. Acesse o app diretamente (sem PIN nesta fase).
4. Vá na aba **Importar** e carregue a planilha inicial.
5. Use a aba **Requisições** para editar ou criar novos registros.
6. Use os filtros na sidebar para segmentar dados.
7. Vá em **Dashboard** para métricas e exportações.

---

## 📌 Guia completo passo a passo (do zero até uso no trabalho)

### ✅ Parte A — Preparar tudo em casa (ou qualquer computador)
1. **Instale o Python 3.10+**  
   - Baixe em: https://www.python.org/downloads/  
   - Durante a instalação, marque a opção **“Add Python to PATH”**.

2. **Abra um terminal e vá até a pasta do projeto**  
   ```bash
   cd /caminho/para/COMPRAS
   ```

3. **Crie o ambiente virtual**  
   ```bash
   python -m venv .venv
   ```

4. **Ative o ambiente**  
   - **Windows**:
     ```bash
     .venv\Scripts\activate
     ```
   - **Linux/Mac**:
     ```bash
     source .venv/bin/activate
     ```

5. **Instale as dependências**  
   ```bash
   pip install -r requirements.txt
   ```

6. **Inicie o app**  
   ```bash
   streamlit run app.py
   ```

7. **Acesse no navegador**  
   - O terminal vai mostrar algo como:
     ```
     Local URL: http://localhost:8501
     ```
   - Use essa URL no navegador.

8. **Acesse sem autenticação** (temporário nesta fase).

---

### ✅ Parte B — Usar no trabalho depois
Você **não precisa reconfigurar tudo** se levar a pasta já pronta com `.venv` e dependências instaladas.

1. **Copie a pasta inteira para o computador do trabalho**  
   (por exemplo via pendrive ou rede).

2. **Abra terminal na pasta do projeto**  
   ```bash
   cd /caminho/para/COMPRAS
   ```

3. **Ative o ambiente**  
   - **Windows**:
     ```bash
     .venv\Scripts\activate
     ```
   - **Linux/Mac**:
     ```bash
     source .venv/bin/activate
     ```

4. **Rode o app**  
   ```bash
   streamlit run app.py
   ```

5. **Acesse a URL local**  
   Normalmente:
   ```
   http://localhost:8501
   ```

---

## ❓Posso terminar em casa e abrir no trabalho só com a URL?
Você pode **terminar tudo em casa**, sim.  
Mas a URL (`http://localhost:8501`) **só funciona na máquina que está rodando o Streamlit**.

✅ **Em casa:** funciona localmente.  
✅ **No trabalho:** funciona localmente também, **desde que você rode o app lá**.

➡️ Portanto, **não dá para abrir só pela URL em outra máquina sem rodar o app naquela máquina**.

Se quiser abrir o app de qualquer lugar sem rodar localmente, aí sim seria necessário:
- hospedar em servidor ou
- manter sua máquina ligada e expor a porta.

Mas para uso simples no trabalho, basta rodar o comando localmente e abrir o navegador.

---

## 🚀 Deploy direto no Railway (app + Postgres)

### ✅ 1) Crie o banco Postgres no Railway
1. Acesse https://railway.app e crie uma conta.
2. Crie um novo projeto e adicione um **PostgreSQL**.
3. Copie a variável **DATABASE_URL** fornecida pelo Railway.

### ✅ 2) Suba o app no Railway (usando o GitHub)
1. Suba este repositório para o GitHub.
2. No Railway, crie um novo serviço **Web** a partir do GitHub.
3. Aponte para este repositório e confirme o deploy.
4. O Railway usa o `Procfile` para iniciar o app.
5. O Python está fixado em **3.12.3** via `.python-version` (evita erro de build com pandas).

### ✅ 3) Configure as variáveis de ambiente
No serviço **Web** do Railway, adicione:
- `DATABASE_URL` (use a URL do Postgres criado no passo 1)
> Dica: se o app abrir sem erro de banco, significa que o `DATABASE_URL` está sendo usado corretamente.

### ✅ 4) Acesse pela URL pública
- O Railway gera uma URL pública para seu app (no serviço Web).
- O app e o banco ficam no **mesmo provedor** e os dados são persistentes.
