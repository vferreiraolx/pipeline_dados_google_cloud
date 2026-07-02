# Guia de Operação do Pipeline de Dados

## Visão Geral

O Pipeline de Dados do Planejamento Comercial automatiza o fluxo de extração, transformação e carga (ETL) de dados para o time. O fluxo completo é:

1. **Extração**: Conecta ao Trino e extrai dados das tabelas Hive configuradas
2. **Upload GCS**: Envia os arquivos CSV extraídos para o Google Cloud Storage
3. **Carga BigQuery**: Carrega os dados do GCS nas tabelas BigQuery correspondentes
4. **Tabelas Derivadas**: Executa queries SQL para gerar visões consolidadas
5. **Exportação Sheets**: Exporta os resultados para planilhas Google Sheets

Toda a configuração é feita via arquivo `config.yaml` na raiz do projeto. Não é necessário alterar código Python para as operações descritas abaixo.

---

## Como Adicionar uma Nova Tabela-Fonte

Para incluir uma nova tabela Hive no pipeline, edite a seção `extraction.tables` do arquivo `config.yaml`.

### Passo a Passo

1. Abra o arquivo `config.yaml` na raiz do projeto
2. Localize a seção `extraction.tables`
3. Adicione um novo item à lista seguindo a estrutura abaixo
4. Salve o arquivo

### Estrutura de uma Tabela-Fonte

```yaml
- full_name: "hive.schema.nome_da_tabela"   # Nome completo (catálogo.schema.tabela)
  short_name: "nome_da_tabela"              # Nome curto (usado para nomes de arquivo)
  partition_column: "dt"                     # Coluna de partição para extração incremental
```

### Exemplo Prático

Suponha que você queira adicionar a tabela `hive.planejamento.re_silver_metas_comerciais`:

```yaml
extraction:
  batch_size: 100000
  tables:
    - full_name: "hive.planejamento.re_gold_receita_unificado_air"
      short_name: "re_gold_receita_unificado_air"
      partition_column: "dt"
    - full_name: "hive.planejamento.re_silver_receita_cb_air"
      short_name: "re_silver_receita_cb_air"
      partition_column: "dt"
    - full_name: "hive.planejamento.re_silver_planos_periodicos_cb"
      short_name: "re_silver_planos_periodicos_cb"
      partition_column: "dt"
    # Nova tabela adicionada:
    - full_name: "hive.planejamento.re_silver_metas_comerciais"
      short_name: "re_silver_metas_comerciais"
      partition_column: "dt"
```

### O que acontece após adicionar

- Na **primeira execução**, o pipeline fará uma extração completa (todos os registros da tabela)
- Nas **execuções seguintes**, fará extração incremental (somente a partição `dt` do dia atual)
- O arquivo será salvo no GCS como `re_silver_metas_comerciais/re_silver_metas_comerciais_YYYY-MM-DD.csv`
- Uma tabela BigQuery será criada automaticamente em `conect-python-g-sheets.planejamento_comercial.re_silver_metas_comerciais`

### Regras Importantes

- O `short_name` deve ser único entre todas as tabelas
- O `short_name` não pode conter espaços ou caracteres especiais (use apenas letras, números e underscore)
- O `partition_column` geralmente é `"dt"` para tabelas do Hive no ambiente OLX

---

## Como Adicionar/Modificar uma Tabela Derivada

Tabelas derivadas são criadas a partir de queries SQL executadas sobre as tabelas já carregadas no BigQuery. São úteis para criar visões consolidadas de negócio.

### Passo a Passo para Adicionar

1. Crie um arquivo SQL na pasta `sql/` com a query de transformação
2. Edite o `config.yaml` para adicionar a entrada na seção `derived_tables`
3. Salve ambos os arquivos

### Passo 1: Criar o Arquivo SQL

Crie um arquivo na pasta `sql/` com nome descritivo. Exemplo: `sql/receita_por_produto.sql`

```sql
-- Tabela derivada: receita_por_produto
-- Consolida receita por produto a partir das tabelas importadas

SELECT
    produto,
    categoria,
    SUM(valor_receita) AS receita_total,
    COUNT(DISTINCT cliente_id) AS clientes_unicos,
    dt
FROM `conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air`
GROUP BY produto, categoria, dt
ORDER BY receita_total DESC
```

### Passo 2: Adicionar ao config.yaml

Localize a seção `derived_tables` e adicione um novo item:

```yaml
derived_tables:
  - name: "receita_consolidada"
    destination: "conect-python-g-sheets.planejamento_comercial.receita_consolidada"
    order: 1
    sql_file: "sql/receita_consolidada.sql"
  # Nova tabela derivada:
  - name: "receita_por_produto"
    destination: "conect-python-g-sheets.planejamento_comercial.receita_por_produto"
    order: 2
    sql_file: "sql/receita_por_produto.sql"
```

### Estrutura de uma Tabela Derivada

```yaml
- name: "nome_identificador"                    # Nome descritivo (único)
  destination: "projeto.dataset.nome_tabela"    # Tabela de destino no BigQuery (completa)
  order: 1                                      # Ordem de execução (1 = primeira)
  sql_file: "sql/nome_do_arquivo.sql"           # Caminho do arquivo SQL (relativo à raiz)
```

### Exemplo: Modificar uma Tabela Derivada Existente

Para alterar a lógica de uma tabela derivada, basta editar o arquivo SQL correspondente. Exemplo — alterar `sql/receita_consolidada.sql`:

```sql
-- Query atualizada com filtro de período
SELECT
    produto,
    SUM(valor_receita) AS receita_total,
    dt
FROM `conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air`
WHERE dt >= '2024-01-01'
GROUP BY produto, dt
```

Não é necessário alterar o `config.yaml` se a tabela de destino permanecer a mesma.

### Regras Importantes

- O campo `order` define a sequência de execução — tabelas derivadas que dependem de outras devem ter `order` maior
- O modo de escrita é sempre **WRITE_TRUNCATE** (substituição completa da tabela de destino)
- A query SQL deve referenciar tabelas com o nome completo `projeto.dataset.tabela`
- O `name` deve ser único entre todas as tabelas derivadas

---

## Como Alterar Mapeamentos de Google Sheets

Os mapeamentos definem quais tabelas BigQuery são exportadas para quais planilhas Google Sheets.

### Passo a Passo

1. Abra o arquivo `config.yaml`
2. Localize a seção `sheets_export.mappings`
3. Adicione, remova ou modifique entradas conforme necessário
4. Salve o arquivo

### Estrutura de um Mapeamento

```yaml
- table: "projeto.dataset.nome_tabela"    # Tabela BigQuery de origem (nome completo)
  spreadsheet_id: "ID_DA_PLANILHA"        # ID da planilha Google Sheets
  sheet_name: "Nome da Aba"               # Nome da aba de destino na planilha
```

### Como Encontrar o ID da Planilha

O ID da planilha é a sequência de caracteres na URL do Google Sheets entre `/d/` e `/edit`:

```
https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/edit#gid=0
                                       └─────────────────────────────┘
                                         Este é o spreadsheet_id
```

### Exemplo Prático: Adicionar um Novo Mapeamento

Suponha que você criou a tabela derivada `receita_por_produto` e quer exportá-la para uma planilha:

```yaml
sheets_export:
  retry_attempts: 3
  mappings:
    - table: "conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air"
      spreadsheet_id: "1ABC..."
      sheet_name: "Receita Unificado"
    - table: "conect-python-g-sheets.planejamento_comercial.receita_consolidada"
      spreadsheet_id: "1ABC..."
      sheet_name: "Consolidado"
    # Novo mapeamento:
    - table: "conect-python-g-sheets.planejamento_comercial.receita_por_produto"
      spreadsheet_id: "1XyZ_abc123_definir_id_aqui"
      sheet_name: "Receita por Produto"
```

### Exemplo: Alterar a Aba de Destino

Para mudar a aba onde os dados são exportados, basta alterar o campo `sheet_name`:

```yaml
    - table: "conect-python-g-sheets.planejamento_comercial.receita_consolidada"
      spreadsheet_id: "1ABC..."
      sheet_name: "Consolidado - v2"   # Aba renomeada
```

### Exemplo: Exportar para uma Planilha Diferente

Para mover a exportação para outra planilha, altere o `spreadsheet_id`:

```yaml
    - table: "conect-python-g-sheets.planejamento_comercial.receita_consolidada"
      spreadsheet_id: "1NoVo_Id_Da_Planilha_Aqui"   # Nova planilha
      sheet_name: "Consolidado"
```

### Regras Importantes

- A tabela BigQuery referenciada em `table` já deve existir (seja fonte ou derivada)
- O `spreadsheet_id` deve ser de uma planilha compartilhada com a service account do pipeline
- O `sheet_name` deve corresponder exatamente ao nome da aba na planilha (case-sensitive)
- A exportação **substitui integralmente** o conteúdo da aba de destino a cada execução

---

## Erros Comuns e Soluções

### Erro de Sintaxe no config.yaml

**Mensagem**: `Erro de validação no config.yaml: campo X ausente ou inválido`

**Causa**: YAML é sensível a indentação e formatação.

**Solução**:
- Verifique se a indentação está correta (use 2 espaços, nunca TABs)
- Confirme que strings com caracteres especiais estão entre aspas
- Valide o YAML em um editor com destaque de sintaxe

**Exemplo de erro comum** (indentação incorreta):
```yaml
# ERRADO - indentação incorreta
extraction:
tables:   # Falta a indentação
  - full_name: "..."
```

```yaml
# CORRETO
extraction:
  tables:
    - full_name: "..."
```

### Tabela Não Encontrada no Trino

**Mensagem**: `[EXTRAÇÃO] [FALHA] Tabela: nome_tabela | Tabela não encontrada`

**Causa**: O `full_name` no config não corresponde a uma tabela existente no Hive.

**Solução**:
- Verifique se o nome está correto (catálogo.schema.tabela)
- Confirme que a tabela existe no Trino executando: `SHOW TABLES IN hive.planejamento`

### Falha de Upload para GCS

**Mensagem**: `[UPLOAD_GCS] [FALHA] Tabela: nome_tabela | Timeout após 3 tentativas`

**Causa**: Problemas de rede ou permissão no bucket GCS.

**Solução**:
- Verifique se o bucket `teste-extracao-trino` está acessível
- Confirme que a service account tem permissão de escrita no bucket
- O arquivo local é mantido para retry manual

### Falha na Exportação para Sheets

**Mensagem**: `[EXPORTAÇÃO_SHEETS] [FALHA] Tabela: nome_tabela | Planilha não encontrada`

**Causa**: O `spreadsheet_id` está incorreto ou a planilha não está compartilhada com a service account.

**Solução**:
- Verifique se o ID da planilha está correto
- Compartilhe a planilha com o e-mail da service account do projeto
- Confirme que o nome da aba (`sheet_name`) existe na planilha

### Tabela Derivada com Erro SQL

**Mensagem**: `[DERIVADAS] [FALHA] Tabela: nome_derivada | Syntax error in SQL`

**Causa**: O arquivo SQL contém erro de sintaxe ou referencia tabelas inexistentes.

**Solução**:
- Teste a query diretamente no console do BigQuery antes de colocar no pipeline
- Verifique se todas as tabelas referenciadas no SQL já existem no BigQuery
- Confirme que o caminho `sql_file` no config aponta para o arquivo correto

### Credenciais Ausentes

**Mensagem**: `Variáveis de ambiente ausentes: TRINO_USER, TRINO_PASSWORD`

**Causa**: As variáveis de ambiente com credenciais AD não estão configuradas.

**Solução**:
- Verifique se as variáveis de ambiente estão definidas no ambiente de execução
- Para Cloud Functions, configure via `gcloud functions deploy --set-env-vars`

---

## Formato dos Logs

O pipeline gera logs estruturados em português para cada etapa da execução. O formato é:

```
[{timestamp}] [{etapa}] [{status}] Tabela: {nome_tabela} | Registros: {contagem} | {mensagem}
```

### Campos do Log

| Campo | Descrição | Exemplo |
|-------|-----------|---------|
| `timestamp` | Data/hora no formato ISO 8601 | `2024-01-15T10:00:05` |
| `etapa` | Fase do pipeline | `EXTRAÇÃO`, `UPLOAD_GCS`, `CARGA_BQ`, `DERIVADAS`, `EXPORTAÇÃO_SHEETS` |
| `status` | Resultado da operação | `SUCESSO` ou `FALHA` |
| `nome_tabela` | Tabela sendo processada | `re_gold_receita_unificado_air` |
| `contagem` | Número de registros processados | `45230` |
| `mensagem` | Descrição adicional | `Extração incremental concluída` |

### Exemplos de Logs

**Execução bem-sucedida:**
```
[2024-01-15T10:00:05] [EXTRAÇÃO] [SUCESSO] Tabela: re_gold_receita_unificado_air | Registros: 45230 | Extração incremental concluída
[2024-01-15T10:01:12] [UPLOAD_GCS] [SUCESSO] Tabela: re_gold_receita_unificado_air | Registros: 45230 | Upload concluído
[2024-01-15T10:02:30] [CARGA_BQ] [SUCESSO] Tabela: re_gold_receita_unificado_air | Registros: 45230 | Carga incremental concluída
[2024-01-15T10:03:00] [DERIVADAS] [SUCESSO] Tabela: receita_consolidada | Registros: 12500 | Transformação concluída
[2024-01-15T10:03:45] [EXPORTAÇÃO_SHEETS] [SUCESSO] Tabela: receita_consolidada | Registros: 12500 | Exportação concluída
```

**Execução com falha:**
```
[2024-01-15T10:00:12] [EXTRAÇÃO] [FALHA] Tabela: re_silver_receita_cb_air | Registros: 0 | Timeout após 3 tentativas de conexão
[2024-01-15T10:00:12] [UPLOAD_GCS] [FALHA] Tabela: re_silver_receita_cb_air | Registros: 0 | Extração não concluída, upload não realizado
```

---

## Resumo Rápido de Operações

| Operação | O que editar | Onde |
|----------|-------------|------|
| Adicionar tabela-fonte | `config.yaml` → `extraction.tables` | Adicionar item na lista |
| Adicionar tabela derivada | Criar arquivo em `sql/` + `config.yaml` → `derived_tables` | Criar SQL + adicionar item |
| Modificar tabela derivada | Arquivo SQL em `sql/` | Editar a query |
| Adicionar exportação Sheets | `config.yaml` → `sheets_export.mappings` | Adicionar item na lista |
| Alterar aba de destino | `config.yaml` → `sheets_export.mappings` → `sheet_name` | Editar valor |
| Alterar planilha de destino | `config.yaml` → `sheets_export.mappings` → `spreadsheet_id` | Editar valor |
