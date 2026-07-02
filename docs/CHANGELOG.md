# Changelog — Ajustes no Pipeline Receita 5.0

Registro dos ajustes feitos no código durante a fase de validação e otimização.

---

## 2026-07-02 — VPC Connector & Eliminação de VPN

### 1. Cloud Function `pipeline-dados-planejamento` — Deploy com VPC (PRODUÇÃO)

**Status**: ✅ ATIVO | Revisão: `pipeline-dados-planejamento-00008-vux`

**O que foi feito**:
- Deploy da Cloud Function Gen2 com VPC Connector `trino-connector` (us-east4)
- Egress settings: `ALL_TRAFFIC` — todo tráfego passa pelo VPC, sem necessidade de VPN
- Autenticação: variáveis `TRINO_USER` / `TRINO_PASSWORD` configuradas como env vars na função
- Validado: extração e carga de 844.994 registros de `re_gold_receita_unificado_air` → BigQuery

**Arquitetura do pipeline em produção**:
```
Cloud Scheduler → Cloud Function (VPC Connector) → Trino Gateway → GCS → BigQuery
```

---

### 2. `src/bigquery_loader.py` — Estratégia de carga snapshot

**Problema**: Carga incremental (`DELETE + WRITE_APPEND`) falhava com schema mismatch — coluna `vigencia_bt` mudou de `INTEGER` para `STRING` no Trino.

**Correção**: `load_incremental()` trocado para `WRITE_TRUNCATE` (snapshot completo por execução). Sem `DELETE` prévio.

**Testes**: 21/21 passando (atualizados para refletir estratégia snapshot).

---

### 3. Validação end-to-end sem VPN — PROVA DOCUMENTADA

**Teste executado com VPN corporativa desligada:**

| Campo | Evidência |
|-------|-----------|
| Execution ID | `bkCES3cqjsMr` |
| Invocado em | 2026-07-02T22:48:24 UTC (VPN OFF) |
| Conexão Trino | `[CONEXÃO] [SUCESSO]` — 22:48:26 UTC |
| Extração | `[EXTRAÇÃO] [SUCESSO]` — **845.840 rows** — 22:49:03 UTC |
| Mecanismo | VPC Connector `trino-connector` us-east4 · ALL_TRAFFIC |

---

### 4. Purga completa de VPN — Código e Documentação

**Problema**: Dependências e referências a VPN distribuídas em múltiplos arquivos.

**Arquivos atualizados**:
- `pipeline_local.py` — removido `credenciais.env`, `AD_USER_NAME`/`AD_USER_PASSWORD` → `TRINO_USER`/`TRINO_PASSWORD`; docstring atualizada para "LEGADO, sem VPN"
- `credenciais.example.env` — atualizado para `TRINO_USER`/`TRINO_PASSWORD`; instrução de uso correta
- `README.md` — pipeline local: removido requisito `credenciais.env`; troubleshooting atualizado
- `docs/CHANGELOG.md` — pendência VPC marcada como concluída ✅
- `docs/OPERACAO.md` — sem referências a VPN; usa `TRINO_USER`/`TRINO_PASSWORD`
- `docs/pipeline_overview.html` — VPN removida como requisito; status VPC atualizado
- `docs/validadores_query/README.md` — `validar_trino_snapshot.py` marcado como legado
- `tests/unit/test_trino_extractor.py` — corrigido teste para `DATE 'YYYY-MM-DD'` (literal SQL tipado)

**Suíte de testes**: **95/95 passando**.

---

## 2026-06-29 — Sessão de hoje

### 1. `cb_pagamentos.sql` — Correção `id_migracao_pro_field`

**Problema**: A coluna `id_migracao_pro_field` retornava apenas 38 "Sim" (vs 2.989 no Sheets). A lógica original usava LAG do mês atual (só detecta migração pontual).

**Causa raiz**: O Sheets faz XLOOKUP na aba "Transferências" (lista histórica de todos que já migraram pro Field). O SQL usava `status_migrado = 'Migrado' AND canal_conta = 'Field'` — que só pega quem migrou **naquele mês específico**.

**Correção**: Adicionada CTE `transferencias_historico` que busca todos advertisers que migraram pro Field a partir de dez/2025:

```sql
transferencias_historico AS (
  SELECT DISTINCT advertiser_id
  FROM dados
  WHERE status_migrado = 'Migrado' AND canal_conta = 'Field'
    AND mes_base >= DATE '2025-12-01'
)
```

**Resultado**: 3.130 "Sim" (vs 2.989 no Sheets — margem de ~4.7% por snapshot). Valores financeiros batem 100%.

---

### 2. `bd_full_v2.sql` — Otimização de performance

**Problema**: A `bd_full.sql` original levava ~40 minutos pra executar (subqueries correlacionadas — 40+ subselects × 8.000 linhas de dimensões).

**Correção**: Reescrita completa usando CTEs pré-agregadas + LEFT JOIN:
- Cada métrica é calculada UMA VEZ com GROUP BY
- O SELECT final só faz JOINs em memória

**Resultado**: De ~40 minutos para **3.8 segundos** (630x mais rápido). Valores 100% idênticos à v1.

**Arquivo**: `sql/bd_full_v2.sql` (validada, pronta pra substituir a v1)

---

### 3. `bd_full.sql` (v1) — Adição de 15 colunas faltantes

**Problema**: A query não tinha todas as colunas do Sheets (faltavam # Base Final, $ Cancelamento Total, $ Base Final, # Pagamentos, # Campanha/SVA, CHURN IN/OUT BI, Chave).

**Colunas adicionadas**:
- AC: # Pagamentos Adiantados
- AD: # Pagamentos no mês (+ Planos Periódicos PAID)
- AE: # Pagamentos Transcorridos
- AF: # Pagamento Campanha (usando `cordenador`, não `coordenador_ajustado`)
- AG: # Pagamento SVA
- AO: $ Cancelamento total Pago
- BI: CHURN IN # (filtro adicional `mes_base = dt_cancelado`)
- BJ: CHURN IN $
- BK: CHURN OUT #
- BL: CHURN OUT $
- BP: Chave EQUIPE X COORDENADOR

**Nota**: Colunas J (# Base Final), P ($ Cancelamento total), S ($ Base Final), AR ($ Base Final Pago) são fórmulas derivadas de outras colunas — implementadas na v2.

---

### 4. `receita_enriquecida.sql` — Integração Cohort (radar)

**Problema**: Colunas `Data_Vencimento_Cohort` e `Data_Pagamento_Cohort` não existiam na receita_enriquecida. O `volume_transcorrido` usava `ultimo_mes_pagamento` como proxy (~96% precisão).

**Correção**:
- Criado `sql/radar_cohort.sql` — extrai `expiration_date` e `payment_date` da `re_bronze_radar` (mínimo de colunas: advertiser_id, mes_base, 2 datas)
- Adicionado LEFT JOIN na receita_enriquecida com `radar_cohort`
- Expõe `data_vencimento_cohort` e `data_pagamento_cohort`
- Recalcula `volume_transcorrido` usando `data_pagamento_cohort` real

**Fórmula implementada (tradução exata do Sheets)**:
```sql
CASE
  WHEN day_base >= DATE_SUB(DATE_ADD(LAST_DAY(mes_base), INTERVAL 1 DAY), INTERVAL 6 DAY)
    AND day_base <= LAST_DAY(mes_base)
    AND (data_pagamento_cohort IS NULL
         OR EXTRACT(MONTH FROM data_pagamento_cohort) = EXTRACT(MONTH FROM DATE_ADD(mes_base, INTERVAL 1 MONTH)))
    AND (dt_cancelado IS NULL
         OR EXTRACT(MONTH FROM dt_cancelado) <> EXTRACT(MONTH FROM mes_base)
         OR EXTRACT(YEAR FROM dt_cancelado) <> EXTRACT(YEAR FROM mes_base))
  THEN faturado_mes
  ELSE 0
END
```

---

### 5. `desconto_faseado.sql` — Filtro por Real Estate

**Problema**: Query retornava 56.995 linhas (todos segmentos). A aba do Sheets tem ~3.265 (só RE).

**Correção**: Adicionado INNER JOIN com advertisers que existem na `re_gold_receita_unificado_air` (filtra só Real Estate):

```sql
INNER JOIN advertisers_re re ON od.advertiser_id = re.advertiser_id
```

**Resultado**: ~7 advertisers com desconto ativo (flag funcional pra receita_enriquecida).

---

### 6. `config.yaml` e `pipeline_local.py` — Novos campos

**Adições**:
- `use_max_dt: true` pra `re_silver_planos_periodicos_cb`
- `radar_cohort` como extração custom
- `planos_periodicos` como tabela derivada (order 6)
- Suporte a `sql_file` e `use_max_dt` no `SourceTableConfig`

---

### 7. `src/orchestrator.py` e `src/trino_extractor.py` — Suporte a SQL customizado

**Problema**: O orchestrator não suportava extrações com SQL customizado (desconto_faseado, radar_cohort) nem `use_max_dt`.

**Correção**:
- `TrinoExtractor.extract_custom(query, output_path)` — novo método
- `Orchestrator._process_source_tables()` — lógica condicional pra custom SQL e use_max_dt
- `SourceTableConfig` — campos `sql_file` e `use_max_dt` opcionais
- `ConfigManager` — relaxou validação de `partition_column` (não obrigatório pra custom)

---

## Relatório de Paridade (Jun/2026)

| Tabela | Precisão | Nota |
|--------|----------|------|
| receita_enriquecida | 100% | Faturado/pago no centavo |
| cb_pagamentos | 100% | Valores financeiros idênticos |
| bd_full | 99.7% | ±0.3% por snapshot |
| diarizacao | ~97% | Diferença de snapshot confirmada |
| Cohort (volume_transcorrido) | ~96% → pendente revalidação | Integração radar_cohort feita, aguardando re-execução |

---

## Pendências

1. Rodar pipeline com `radar_cohort` e revalidar volume_transcorrido
2. Substituir `bd_full.sql` pela `bd_full_v2.sql` após validação final
3. Investigar divergência Online (-6.2% # Novos) — provável mismatch na CTE pp_equipe
4. ~~Aguardar VPC Connector da infra pra deploy em Cloud Run~~ ✅ **VPC Connector `trino-connector` deployado em us-east4. Cloud Function `pipeline-dados-planejamento` em produção — sem necessidade de VPN.**
