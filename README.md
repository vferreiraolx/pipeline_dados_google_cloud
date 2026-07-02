# Pipeline de Dados - Planejamento Comercial

Pipeline que extrai dados do Data Lake (Trino) e gera tabelas automatizadas no BigQuery para o time de Planejamento Comercial da RE.

---

## Como funciona (resumo simples)

```
Trino (banco de dados) → GCS → BigQuery (armazém na nuvem) → Tabelas calculadas → Google Sheets
```

O pipeline faz 3 coisas:
1. **Extrai** dados brutos do Trino (nosso banco de dados interno)
2. **Calcula** tabelas derivadas usando SQL (receita enriquecida, BD FULL, diarização, etc.)
3. **Exporta** os resultados para Google Sheets (quando configurado)

---

## Modos de Execução

### 1. Cloud Function (principal — produção)

Pipeline deployado como Cloud Function com VPC Connector pra acessar o Trino sem VPN.

**URL**: `https://us-east4-conect-python-g-sheets.cloudfunctions.net/pipeline-dados-planejamento`

**Disparar manualmente** (Cloud Shell):
```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://us-east4-conect-python-g-sheets.cloudfunctions.net/pipeline-dados-planejamento"
```

**Ver logs**:
```bash
gcloud functions logs read pipeline-dados-planejamento \
  --region=us-east4 --project=conect-python-g-sheets --limit=20
```

**Redeploy (após editar config/sql/código)**:
```bash
gcloud functions deploy pipeline-dados-planejamento \
  --gen2 --runtime=python311 --region=us-east4 --source=. \
  --entry-point=pipeline_handler --trigger-http \
  --vpc-connector=projects/conect-python-g-sheets/locations/us-east4/connectors/trino-connector \
  --egress-settings=all --timeout=540s --memory=4Gi \
  --project=conect-python-g-sheets --quiet
```

**Adicionar nova tabela**:
1. Editar `config.yaml` na seção `extraction.tables`
2. Rodar o comando de redeploy acima
3. A tabela aparece em `planejamento_comercial.nome_curto` no BigQuery

---

### 2. Pipeline Local (fallback — requer VPN)

Pra quando a cloud não funciona, ou pra testes rápidos.

**Pré-requisitos**:
- VPN conectada
- Python com dependências (`pip install -r requirements.txt`)
- Arquivo `credenciais.env` configurado (ver `credenciais.example.env`)
- Autenticação GCP (`gcloud auth application-default login`)

**Rodar pipeline completo** (extração + cálculos):
```bash
python pipeline_local.py
```

**Rodar só os cálculos** (sem extrair do Trino — usa dados já carregados no BQ):
```bash
python pipeline_local.py --derivadas
```

**Tempo estimado**:
- Pipeline completo: ~15 minutos
- Só derivadas: ~2-5 minutos

---

## Configuração: `config.yaml`

### Adicionar tabela padrão (SELECT * com filtro dt):
```yaml
extraction:
  tables:
    - full_name: "hive.schema.nome_da_tabela"
      short_name: "nome_curto"
      partition_column: "dt"
```

### Usar MAX(dt) em vez do dia atual:
```yaml
      use_max_dt: true
```

### Query SQL customizada:
```yaml
    - full_name: "custom_sql"
      short_name: "nome_curto"
      partition_column: ""
      sql_file: "sql/nome_do_arquivo.sql"
```

### Adicionar tabela derivada (SQL que roda no BQ):
```yaml
derived_tables:
  - name: "nome_tabela"
    destination: "conect-python-g-sheets.planejamento_comercial.nome_tabela"
    order: 10
    sql_file: "sql/nome_tabela.sql"
```

---

## Estrutura de pastas

```
projeto_sheets/
├── main.py                  # Entry point da Cloud Function
├── pipeline_local.py        # Script pra rodar local (com VPN)
├── config.yaml              # Configuração: quais tabelas extrair e processar
├── requirements.txt         # Dependências Python
├── .gcloudignore            # Arquivos excluídos do deploy
├── .gitignore               # Arquivos excluídos do git
│
├── sql/                     # Queries SQL que geram as tabelas
│   ├── receita_consolidada.sql
│   ├── cb_pagamentos.sql
│   ├── receita_enriquecida.sql
│   ├── bd_full.sql / bd_full_v2.sql
│   ├── bd_planos_uf.sql
│   ├── bd_planos_mensais_sva.sql
│   ├── bd_planos_periodicos.sql
│   ├── planos_periodicos.sql
│   ├── diarizacao.sql
│   ├── desconto_faseado.sql
│   ├── radar_cohort.sql
│   └── transferencias.sql
│
├── src/                     # Código fonte do pipeline
│   ├── orchestrator.py      # Coordena todo o fluxo
│   ├── trino_extractor.py   # Conecta e extrai do Trino
│   ├── bigquery_loader.py   # Carrega dados no BigQuery
│   ├── gcs_uploader.py      # Upload pra Google Cloud Storage
│   ├── sheets_exporter.py   # Exporta pra Google Sheets
│   ├── config_manager.py    # Lê e valida o config.yaml
│   ├── state_manager.py     # Controla estado de extração
│   ├── models.py            # Estruturas de dados
│   ├── logger.py            # Logs formatados
│   └── exceptions.py        # Exceções customizadas
│
├── docs/                    # Documentação
│   ├── DEPLOY_REPORT.md     # Relatório do deploy na cloud
│   ├── OPERACAO.md          # Guia de operação
│   └── CHANGELOG.md         # Histórico de mudanças
│
└── tests/                   # Testes automatizados
```

---

## Troubleshooting

### Cloud Function

| Problema | Causa | Solução |
|----------|-------|---------|
| `upstream request timeout` | Extração demora mais que 540s | Normal pra tabelas grandes. Verifique logs — a extração pode ter completado parcialmente |
| `Service Unavailable (503)` | Memória insuficiente ou cold start | Verifique logs. Se `Memory limit exceeded`, aumente `--memory` no deploy |
| `403 Forbidden` | Token expirado ou function requer auth | Use `curl -H "Authorization: Bearer $(gcloud auth print-identity-token)"` |
| `PERMISSION_DENIED` no deploy | Org Policy bloqueando | Pedir ao time de infra |

### Pipeline Local

| Problema | Causa | Solução |
|----------|-------|---------|
| `Connection timed out` no Trino | VPN não conectada | Conecte a VPN e tente novamente |
| `AD_USER_NAME não definidas` | `credenciais.env` não configurado | Crie baseado no `credenciais.example.env` |
| `ERRO bd_full: Unrecognized name` | Tabelas anteriores não geradas | Rode pipeline completo (tabelas são geradas em ordem) |
| Pipeline demora >40 min | Normal pra bd_full na primeira vez | Aguarde ou rode `--derivadas` se dados já estão no BQ |
| Valores divergem do Sheets (<1%) | Snapshot timing (PP atualizado diariamente) | Esperado — re-rode se necessário |
| Valores divergem do Sheets (>5%) | Bug na query SQL | Verifique a lógica da query vs fórmulas do Sheets |

---

## Tabelas geradas (ordem de execução)

| # | Tabela | Descrição |
|---|--------|-----------|
| 1 | receita_consolidada | União de receita unificada + CB |
| 2 | cb_pagamentos | Pagamentos CB com coordenador/canal |
| 3 | receita_enriquecida | Base principal com todas colunas calculadas |
| 4 | bd_planos_uf | Agregação por Canal/Equipe/Região/UF |
| 5 | bd_planos_mensais_sva | Agregação mensal com SVA e migração |
| 6 | planos_periodicos | Planos periódicos processados |
| 7 | bd_planos_periodicos | Agregação dos planos periódicos |
| 8 | bd_full | Tabela completa BD FULL (a mais importante) |
| 9 | diarizacao | Pivot diário NOVO/CHURN/UP/DOWN por canal |

---

## Infra

- **Projeto GCP**: `conect-python-g-sheets`
- **Dataset BigQuery**: `planejamento_comercial`
- **Bucket GCS**: `gs://teste-extracao-trino/`
- **Região**: `us-east4`
- **VPC Connector**: `trino-connector`
- **Trino Host**: `trino-gateway.dataeng.bigdata.olxbr.io:443`
