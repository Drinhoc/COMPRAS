# Changelog

Histórico das principais mudanças do Sistema de Controle de Requisições de Compras.

## [Não lançado] — branch `claude/modest-curie-pdg5ac`

### Adicionado
- **Gerador de Pedido de Compra em PDF** (`src/pedido.py`, reportlab): aba **🧾 Pedido**
  no modal, com escolha da empresa emissora (Engemetal/Bluesun e Engecomp),
  destinatário, itens editáveis, desconto, pagamento, entrega e observações.
  Logos e dados cadastrais reaproveitados dos modelos oficiais (`assets/`).
- **Itens estruturados** (tabela `itens`): planilha editável por requisição com
  total previsto; pode definir o Valor da requisição pela soma dos itens.
- **Aprovação por orçamento específico**, com `APROVADO PARCIAL` e detalhamento;
  botões **✅ aprovar / ❌ rejeitar** por linha de orçamento.
- **Auditoria**: colunas `created_at`/`updated_at` em requisições, exibidas no modal.
- **Vínculo de anexo a orçamento** (`orcamento_id`).
- **Validações**: valores não negativos, Data Compra ≥ Data Solicitação, fornecedor
  obrigatório em `Comprado`/`Concluído`.
- **Ordenação server-side** na lista (por coluna + sentido), válida em todas as páginas.
- **Edição inline** de Status, Empresa, Item, Fornecedor e Valor (salva ao sair da célula).
- **Confirmação antes de excluir** requisição, orçamento e anexo.
- Coluna **REQ-0001 clicável** e **badges 💰/📎 clicáveis** abrindo o modal na aba certa.

### Alterado
- Lista de requisições mais limpa (sem botão extra; ações pela coluna REQ e badges).
- Datas no grid em ISO interno (ordenação correta) exibidas em DD/MM/AAAA.
- Padrão monetário unificado **R$ 1.234,56** em toda a aplicação.
- `update_requisicao` passou a fazer atualização parcial (corrige edição inline).
- Exclusão de requisição agora remove itens/orçamentos/anexos/aprovações em cascata.

### Corrigido
- Reabertura do modal após adicionar orçamento (remontagem da grid via nonce).
- `delete_all_data` resiliente à ausência de `sqlite_sequence`.

### Dependências
- Adicionada `reportlab` (geração de PDF). Requer novo deploy no Railway.
