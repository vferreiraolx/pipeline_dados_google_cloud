# Construção das Tabelas Derivadas — Pipeline Sheets

## Visão Geral

Este pipeline replica as fórmulas do Google Sheets "Dados Receita 4.0" em SQL (BigQuery), eliminando a dependência de SUMIFS/COUNTIFS manuais. Os dados de origem vêm do Trino (`hive.planejamento.*`) e são processados no BigQuery em cadeia.

```
Trino (hive.planejamento)
  → re_gold_receita_unificado_air
  → re_silver_receita_cb_air
  → re_silver_planos_periodicos_cb
  → re_silver_receita_cb_paids_air

BigQuery (tabelas derivadas, em ordem):
  1. receita_consolidada
  2. cb_pagamentos
  3. receita_enriquecida
  4. bd_planos_uf
  5. bd_planos_mensais_sva
  6. bd_planos_periodicos
  7. bd_full
  8. diarizacao
```

---

## 1. receita_consolidada

**Aba Sheets**: Não possui aba direta — é uma UNION de fontes.

**Lógica**: Combina `re_gold_receita_unificado_air` (receita principal) com `re_silver_receita_cb_air` (receita CB) num schema unificado com coluna `fonte` para distinguir origem.

**Complexidade**: Baixa — apenas UNION ALL com mapeamento de colunas.

---

## 2. cb_pagamentos

**Aba Sheets**: "CB Pagamentos"

**Lógica**: Enriquece dados de pagamentos (`re_silver_receita_cb_paids_air`) com informações de coordenador, canal, estado e tamanho vindas da receita unificada (`re_gold_receita_unificado_air`).

**Pontos-chave**:
- JOIN por `advertiser_id` com prioridade para o `mes_base` correspondente ao `mes_pago`
- Calcula `coordenador_ajustado` (Online/ND → usa canal; senão → cordenador)
- Calcula `id_migracao_pro_field` baseado em status_migrado + canal Field
- Desempate via `ROW_NUMBER` quando há múltiplos matches

**Colunas calculadas**:
- K (Coordenador): XLOOKUP por ID&DATA → receita
- L (Canal): idem
- N (Estado Depara): lookup do estado
- O (Tamanho): lookup por ID&DATA
- P (ID Migração Pró Field?): lookup na aba Transferências
- R (Coordenador ajustado): Online/ND → canal; senão → coordenador

---

## 3. receita_enriquecida

**Aba Sheets**: "Receita 4.0/SVA"

**Lógica**: É a tabela BASE que todas as abas BD consultam. Adiciona colunas calculadas à `re_gold_receita_unificado_air`:

**Colunas calculadas**:
| Coluna Sheets | Campo SQL | Lógica |
|---|---|---|
| AK | estado_depara | CASE por UF → macro-região (Sul, MG/ES, RJ, NO/CO, NE, Sp Capital, SP Interior) |
| AL | apoio_qtd_campanha | 1 se pago_mes_campanha ≠ 0 |
| AM | apoio_qtd_sva | 1 se pago_mes_bairro ou pago_mes_topo ≠ 0 |
| AN | id_e_data | CONCAT(advertiser_id, mes_base) |
| AP | tamanho_nr | REGEXP_EXTRACT do número no pacote |
| AS | tamanho_ajustado | Se "Inser" → lookup em `tamanhos_ajustados`; senão faixas: ≤25=PP, ≤80=P, ≤600=M, >600=G |
| AR | coordenador_ajustado | Online→"Online", ND→"ND", senão→cordenador |
| AH | status_migrado | LAG(canal_conta) ≠ canal_conta e não é Novo → "Migrado" |
| AI | aux_canal_out | canal anterior (LAG) |
| AV | coordenador_ajustado_out | coordenador ajustado do mês anterior para migrados |
| AU | id_migracao_pro_field | canal="Field" E advertiser existe na tabela `transferencias` → "Sim" |
| AZ | volume_transcorrido | faturado_mes quando day_base está nos últimos 6 dias do mês E dt_cancelado não é no mesmo mês |

**Correções implementadas**:
- `id_migracao_pro_field`: Antes derivava do status_migrado da mesma linha. Corrigido para usar lookup na tabela `transferencias` (conforme XLOOKUP do Sheets).
- `tamanho_ajustado`: Antes usava fallback genérico para "Inser". Corrigido para buscar na tabela `tamanhos_ajustados`.
- `volume_transcorrido`: Não existia. Implementado conforme fórmula ARRAYFORMULA do Sheets.

---

## 4. bd_planos_uf

**Aba Sheets**: "BD Planos_UF"

**Lógica**: Agregação por Canal × Equipe × Regiao_Macro × Mes_Base × Tamanho × **UF**. Mesma lógica do BD Planos mensais/SVA mas com dimensão UF adicional.

**Métricas**: Base Inicial, Novos, Churn, Up, Down, Recuperados, Campanha, SVA, Pagamentos (adiantados/no_mês/transcorridos), métricas Pago (com filtro status_ts='1-Paid').

**Fontes**: `receita_enriquecida` + `cb_pagamentos`

---

## 5. bd_planos_mensais_sva

**Aba Sheets**: "BD Planos mensais/SVA"

**Lógica**: Mesma estrutura do BD Planos_UF mas SEM dimensão UF e COM colunas de migração IN/OUT completas.

**Métricas adicionais vs bd_planos_uf**:
- Migração IN: # Churn, # Up, # Down, $ Churn, $ Up, $ Down, $ Base, # Base
- Migração OUT: idem usando `coordenador_ajustado_out` e `aux_canal_out`

**Nota sobre AF/AG**: Usam `cordenador` (campo bruto) intencionalmente — confere com a fórmula original do Sheets que referencia `'Receita 4.0/SVA'!AF:AF`.

---

## 6. bd_planos_periodicos

**Aba Sheets**: "BD Planos Periódicos"

**Lógica**: Agrega dados exclusivamente de `re_silver_planos_periodicos_cb` (planos com periodicidade > 1 mês).

**Pontos-chave**:
- Filtra `WHERE dt = MAX(dt)` (snapshot mais recente)
- Calcula estado_depara e equipe_ajustada internamente
- Base Inicial = flat + Churn + ABS(churn do mês)
- Novos = status_recorrente = 'Novo'
- Churn = filtro por `mes_churn` (não por competencia)
- Pagamentos no mês = filtro por `status = 'PAID'`

**Validação**: Campo `valor_mensal` no Trino corresponde à coluna G ("valor_mes") do Sheets — confirmado via DESCRIBE.

---

## 7. bd_full

**Aba Sheets**: "BD FULL"

**Lógica**: A tabela mais complexa. Combina `receita_enriquecida` + `cb_pagamentos` + `planos_periodicos` com dimensão extra **Transferências** (BM).

**Dimensões**: Canal × Equipe × Regiao_Macro × Mes_Base × Tamanho × Transferências

**Regra Transferências**: Quando `id_migracao_pro_field = 'Sim'`, exclui toda contribuição de Planos Periódicos (CASE WHEN...THEN 0).

**Métricas implementadas** (46 colunas):

| Grupo | Colunas | Descrição |
|---|---|---|
| Waterfall # | G, H, I | Base Inicial, Novos, Churn (qtd) |
| Waterfall $ | K, L, M, N, O | Base Inicial, Novos, Up, Down, Churn (valor) |
| Recuperados | Q, R | $ Recuperados, $ Recuperados Novos |
| Campanha | T, U | # e $ Campanha |
| SVA | V, W | # e $ SVA |
| Pagamentos | X, Y, Z | Adiantados, No mês, Transcorridos |
| Pag. detalhe | AA, AB | $ Pag Campanha, $ Pag SVA |
| Up/Down | AH, AI | # Up, # Down |
| **Pago** | AJ–AQ | Base Inicial, Novos, Up, Down, Churn, Recuperados, Recuperados Novos (filtro 1-Paid) |
| **Migração IN** | AS–AX, AY, AZ | Churn/Up/Down IN (#/$), Base IN (#/$) |
| **Migração OUT** | BA–BH | Churn/Up/Down OUT (#/$), Base OUT (#/$) |
| **Volume** | BN, BO | $ e # Volume transcorrido |
| Auxiliar | BP | Chave Equipe×Coordenador |

**Correções implementadas**:
- Adicionadas colunas AJ–AQ (métricas Pago) que não existiam
- Adicionadas colunas AS–AX (Migração IN detalhada) que não existiam
- Adicionadas colunas BA–BF (Migração OUT detalhada) que não existiam
- BN/BO: Substituído `0` fixo pela query real usando `volume_transcorrido`

---

## 8. diarizacao

**Aba Sheets**: "Diarização"

**Lógica**: Pivot diário — cada linha = 1 dia, colunas = classificação × canal.

**Estrutura**:
```
NOVO:      SUMIFS(faturado_mes; day_base=dia; classificacao='Novo'; canal_conta=canal)
CHURN:     SUMIFS(faturado_mes; day_churn=dia; classificacao_churn='CHURN'; canal_conta=canal)
UPGRADE:   SUMIFS(delta; day_base=dia; classificacao='Upgrade'; canal_conta=canal)
DOWNGRADE: SUMIFS(delta; day_base=dia; classificacao='Downgrade'; canal_conta=canal)
```

Canais: Field, Inside, Online, ND (4 colunas por classificação = 16 colunas de métricas).

**Fonte**: Apenas `receita_enriquecida` — gera datas distintas de `day_base` UNION `day_churn` e faz LEFT JOIN com CASE WHEN para pivotar.

---

## Tabelas Auxiliares (não-derivadas)

| Tabela | Origem | Uso |
|---|---|---|
| `transferencias` | Manual / Salesforce | Lista de advertiser_ids que migraram para Field (lookup para id_migracao_pro_field) |
| `tamanhos_ajustados` | Manual | Override de tamanho para pacotes "Inserção" (lookup para tamanho_ajustado) |

---

## Tabelas Trino Complementares Identificadas

| Tabela | Potencial |
|---|---|
| `re_silver_receita_cb_sva_air` | Validação cruzada de SVA (bairro_vip, topo_fixo) |
| `re_silver_itens_faturados` | Reconciliação de faturado_mes |
| `re_campana_migracao_is` | Fonte automatizada para aba Transferências (campo `migrado_f = true`) |
| `re_acompanhamento_sva` | Acompanhamento SVA detalhado |
| `re_silver_carteira_re` | Carteira RE com classificações |
