# Relatório de Colunas - Tabelas Extraídas

**Projeto:** `conect-python-g-sheets`
**Dataset:** `planejamento_comercial`
**Total de tabelas:** 4

---

## re_gold_receita_unificado_air

**Quantidade de colunas:** 33

| # | Coluna | Tipo | Modo | Descrição |
|---|--------|------|------|-----------|
| 1 | `advertiser_id` | STRING | NULLABLE |  |
| 2 | `mes_base` | DATE | NULLABLE |  |
| 3 | `tamanho` | STRING | NULLABLE |  |
| 4 | `pacote` | STRING | NULLABLE |  |
| 5 | `estado` | STRING | NULLABLE |  |
| 6 | `municipio` | STRING | NULLABLE |  |
| 7 | `ultimo_mes_pagamento` | DATE | NULLABLE |  |
| 8 | `status_ts` | STRING | NULLABLE |  |
| 9 | `faturado_mes` | FLOAT | NULLABLE |  |
| 10 | `classificacao` | STRING | NULLABLE |  |
| 11 | `classificacao_rec` | STRING | NULLABLE |  |
| 12 | `classificacao_churn` | STRING | NULLABLE |  |
| 13 | `vigencia_bt` | INTEGER | NULLABLE |  |
| 14 | `dt_cancelado` | DATE | NULLABLE |  |
| 15 | `delta` | FLOAT | NULLABLE |  |
| 16 | `day_base` | DATE | NULLABLE |  |
| 17 | `day_churn` | DATE | NULLABLE |  |
| 18 | `faturado_mes_campanha` | FLOAT | NULLABLE |  |
| 19 | `status_ts_campanha` | STRING | NULLABLE |  |
| 20 | `pago_mes_campanha` | FLOAT | NULLABLE |  |
| 21 | `faturado_mes_bairro_vip` | FLOAT | NULLABLE |  |
| 22 | `status_ts_bairro_vip` | STRING | NULLABLE |  |
| 23 | `pago_mes_bairro` | FLOAT | NULLABLE |  |
| 24 | `faturado_mes_topo_fixo` | FLOAT | NULLABLE |  |
| 25 | `status_ts_topo_fixo` | STRING | NULLABLE |  |
| 26 | `pago_mes_topo` | FLOAT | NULLABLE |  |
| 27 | `total_faturado_sva` | FLOAT | NULLABLE |  |
| 28 | `total_pago_sva` | FLOAT | NULLABLE |  |
| 29 | `canal_conta` | STRING | NULLABLE |  |
| 30 | `dono_conta` | STRING | NULLABLE |  |
| 31 | `dt` | DATE | NULLABLE |  |
| 32 | `cordenador` | STRING | NULLABLE |  |
| 33 | `advertiser_industry` | STRING | NULLABLE |  |

---

## re_silver_receita_cb_air

**Quantidade de colunas:** 20

| # | Coluna | Tipo | Modo | Descrição |
|---|--------|------|------|-----------|
| 1 | `advertiser_id` | STRING | NULLABLE |  |
| 2 | `tamanho` | STRING | NULLABLE |  |
| 3 | `pacote` | STRING | NULLABLE |  |
| 4 | `estado` | STRING | NULLABLE |  |
| 5 | `municipio` | STRING | NULLABLE |  |
| 6 | `mes_base` | DATE | NULLABLE |  |
| 7 | `ultimo_mes_pagamento` | DATE | NULLABLE |  |
| 8 | `status_ts` | STRING | NULLABLE |  |
| 9 | `pago_mes` | FLOAT | NULLABLE |  |
| 10 | `classificacao` | STRING | NULLABLE |  |
| 11 | `classificacao_rec` | STRING | NULLABLE |  |
| 12 | `classificacao_churn` | STRING | NULLABLE |  |
| 13 | `vigencia_bt` | STRING | NULLABLE |  |
| 14 | `dt_cancelado` | DATE | NULLABLE |  |
| 15 | `delta` | FLOAT | NULLABLE |  |
| 16 | `day_base` | DATE | NULLABLE |  |
| 17 | `day_churn` | DATE | NULLABLE |  |
| 18 | `canal_conta` | STRING | NULLABLE |  |
| 19 | `dono_conta` | STRING | NULLABLE |  |
| 20 | `dt` | DATE | NULLABLE |  |

---

## re_silver_planos_periodicos_cb

**Quantidade de colunas:** 26

| # | Coluna | Tipo | Modo | Descrição |
|---|--------|------|------|-----------|
| 1 | `id_conta_olx` | INTEGER | NULLABLE |  |
| 2 | `id_contrato` | INTEGER | NULLABLE |  |
| 3 | `dono_conta` | INTEGER | NULLABLE |  |
| 4 | `dono_contrato` | INTEGER | NULLABLE |  |
| 5 | `competencia` | INTEGER | NULLABLE |  |
| 6 | `valor_total` | INTEGER | NULLABLE |  |
| 7 | `valor_mensal` | INTEGER | NULLABLE |  |
| 8 | `data_inicio` | INTEGER | NULLABLE |  |
| 9 | `data_termino` | INTEGER | NULLABLE |  |
| 10 | `status` | INTEGER | NULLABLE |  |
| 11 | `status_recorrente` | INTEGER | NULLABLE |  |
| 12 | `periodicidade` | INTEGER | NULLABLE |  |
| 13 | `method` | INTEGER | NULLABLE |  |
| 14 | `channel` | INTEGER | NULLABLE |  |
| 15 | `mes_churn` | INTEGER | NULLABLE |  |
| 16 | `dt` | INTEGER | NULLABLE |  |
| 17 | `package_name` | INTEGER | NULLABLE |  |
| 18 | `tamanho` | INTEGER | NULLABLE |  |
| 19 | `coordenador_conta` | INTEGER | NULLABLE |  |
| 20 | `canal` | INTEGER | NULLABLE |  |
| 21 | `estado_conta` | INTEGER | NULLABLE |  |
| 22 | `cidade_conta` | INTEGER | NULLABLE |  |
| 23 | `nome_da_conta` | INTEGER | NULLABLE |  |
| 24 | `email_conta` | INTEGER | NULLABLE |  |
| 25 | `documento_da_conta` | INTEGER | NULLABLE |  |
| 26 | `advertiser_industry` | INTEGER | NULLABLE |  |

---

## re_silver_receita_cb_paids_air

**Quantidade de colunas:** 9

| # | Coluna | Tipo | Modo | Descrição |
|---|--------|------|------|-----------|
| 1 | `advertiser_id` | STRING | NULLABLE |  |
| 2 | `mes_pago` | DATE | NULLABLE |  |
| 3 | `status_ts` | STRING | NULLABLE |  |
| 4 | `antecipado` | FLOAT | NULLABLE |  |
| 5 | `no_mes` | FLOAT | NULLABLE |  |
| 6 | `transcorrido` | FLOAT | NULLABLE |  |
| 7 | `pago_mes` | FLOAT | NULLABLE |  |
| 8 | `day_paid` | DATE | NULLABLE |  |
| 9 | `dt` | DATE | NULLABLE |  |

---
