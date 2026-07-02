# Pipeline de Dados - Planejamento Comercial

Pipeline que extrai dados do Data Lake (Trino) e gera tabelas automatizadas no BigQuery para o time de Planejamento Comercial da RE.

---

## Como funciona (resumo simples)

```
Trino (banco de dados) → BigQuery (armazém na nuvem) → Tabelas calculadas → Google Sheets
```

O pipeline faz 3 coisas:
1. **Extrai** dados brutos do Trino (nosso banco de dados interno)
2. **Calcula** tabelas derivadas usando SQL (receita enriquecida, BD FULL, diarização, etc.)
3. **Exporta** os resultados para Google Sheets (quando configurado)

---

## Como rodar

### Pré-requisitos
- VPN conectada (obrigatório pra acessar o Trino)
- Python instalado com as dependências (`pip install -r requirements.txt`)
- Autenticação GCP configurada (`gcloud auth application-default login`)

### Rodar o pipeline completo (extração + cálculos)
```
python pipeline_local.py
```

### Rodar só os cálculos (sem extrair do Trino)
```
python pipeline_local.py --derivadas
```

### Tempo estimado
- Pipeline completo: ~15 minutos
- Só derivadas: ~2-5 minutos (exceto bd_full que pode levar ~10-40min)

---

## Estrutura de pastas

```
projeto_sheets/
├── main.py                  # Entry point pra Cloud Run (automação na nuvem)
├── pipeline_local.py        # Script pra rodar na sua máquina (com VPN)
├── config.yaml              # Configuração: quais tabelas extrair e processar
├── requirements.txt         # Dependências Python
├── credenciais.env          # Credenciais (NÃO compartilhar)
│
├── sql/                     # Queries SQL que geram as tabelas
│   ├── receita_enriquecida.sql    # Base principal com colunas calculadas
│   ├── cb_pagamentos.sql          # Tabela de pagamentos CB
│   ├── bd_full.sql                # Tabela BD FULL (a mais complexa)
│   ├── bd_planos_uf.sql           # BD por UF
│   ├── bd_planos_mensais_sva.sql  # BD planos mensais/SVA
│   ├── bd_planos_periodicos.sql   # BD planos periódicos
│   ├── diarizacao.sql             # Diarização (pivot diário)
│   ├── receita_consolidada.sql    # Receita consolidada
│   ├── desconto_faseado.sql       # Extração desconto faseado (Salesforce)
│   ├── transferencias.sql         # Lista de transferências de canal
│   ├── tamanhos_ajustados.sql     # Tamanhos com comparação mês anterior
│   └── planos_periodicos.sql      # Planos periódicos processados
│
├── src/                     # Código fonte do pipeline
│   ├── orchestrator.py      # Coordena todo o fluxo
│   ├── trino_extractor.py   # Conecta e extrai do Trino
│   ├── bigquery_loader.py   # Carrega dados no BigQuery
│   ├── gcs_uploader.py      # Upload pra Google Cloud Storage
│   ├── sheets_exporter.py   # Exporta pra Google Sheets
│   ├── config_manager.py    # Lê e valida o config.yaml
│   ├── state_manager.py     # Controla estado (primeira carga vs incremental)
│   ├── models.py            # Estruturas de dados
│   ├── logger.py            # Logs formatados
│   └── exceptions.py        # Exceções customizadas
│
├── docs/                    # Documentação
│   ├── OPERACAO.md          # Guia de operação
│   ├── RELATORIO_COLUNAS.md # Schema das tabelas BigQuery
│   ├── SCHEDULER.md         # Sobre agendamento
│   └── validadores_query/   # Scripts usados pra validar as queries
│
└── tests/                   # Testes automatizados
```

---

## Troubleshooting (problemas comuns)

### "Connection timed out" no Trino
**Causa**: VPN não está conectada.
**Solução**: Conecte a VPN corporativa e tente novamente.

### "Variáveis AD_USER_NAME ou AD_USER_PASSWORD não definidas"
**Causa**: O arquivo `credenciais.env` não está configurado.
**Solução**: Crie o arquivo `credenciais.env` com:
```
AD_USER_NAME=seu.usuario
AD_USER_PASSWORD=sua_senha
```

### "ERRO bd_full: 400 Unrecognized name"
**Causa**: A tabela `receita_enriquecida` ainda não foi gerada.
**Solução**: Rode o pipeline completo (`python pipeline_local.py`) — as tabelas são geradas em ordem.

### Pipeline demora mais de 40 minutos
**Causa**: A `bd_full` usa queries complexas que o BigQuery demora pra processar.
**Solução**: Normal pra primeira execução. Se travar, cancele o job no Console BigQuery e rode `--derivadas` novamente.

### "Tabela X retornou 0 linhas"
**Causa**: O snapshot do dia não está disponível no Trino.
**Solução**: Verifique se a tabela tem dados com `MAX(dt)`. O `re_silver_planos_periodicos_cb` usa `use_max_dt: true` justamente por isso.

### Valores divergem do Sheets
**Causa**: O Sheets recalcula com um snapshot diferente do BigQuery.
**Solução**: Re-rode o pipeline. Se a diferença for <1%, é esperado (timing de snapshot). Se for >5%, verifique a lógica da query.

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

## Quem mantém isso

- **Extração manual**: Alguém do time roda `python pipeline_local.py` com VPN
- **Futuro (automação)**: Cloud Run + VPC Connector (em andamento com infra)
- **Queries derivadas**: Podem ser agendadas via BigQuery Scheduled Queries
