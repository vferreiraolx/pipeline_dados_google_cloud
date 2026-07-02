-- =============================================================================
-- Tabela Derivada: bd_planos_mensais_sva
-- =============================================================================
-- Descrição: Replica a aba "BD Planos mensais/SVA" do Sheets - mesma lógica
--            do BD Planos_UF mas SEM dimensão UF e COM colunas de migração
--            IN/OUT (status_migrado = 'Migrado').
--
-- Dependências:
--   - conect-python-g-sheets.planejamento_comercial.receita_enriquecida
--   - conect-python-g-sheets.planejamento_comercial.cb_pagamentos
--
-- Modo de escrita: WRITE_TRUNCATE (substituição completa a cada execução)
-- =============================================================================

WITH r AS (
  SELECT
    *,
    CASE WHEN tamanho_ajustado = 'PP' THEN 'P' ELSE tamanho_ajustado END AS tamanho_ajustado_full
  FROM `conect-python-g-sheets.planejamento_comercial.receita_enriquecida`
),
cb AS (
  SELECT * FROM `conect-python-g-sheets.planejamento_comercial.cb_pagamentos`
),
dimensoes AS (
  SELECT DISTINCT
    canal_conta AS Canal,
    coordenador_ajustado AS Equipe,
    regionalizacao AS Regiao_Macro,
    mes_base AS Mes_Base,
    tamanho_ajustado_full AS Tamanho
  FROM r
  WHERE canal_conta IS NOT NULL AND canal_conta <> ''
)

SELECT
  d.Canal,
  d.Equipe,
  d.Regiao_Macro,
  d.Mes_Base,
  d.Tamanho,

  -- G: # Base Inicial
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE mes_base = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND (dt_cancelado IS NULL OR dt_cancelado <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
  ) AS base_inicial_qtd,

  -- H: # Novos
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE classificacao = 'Novo'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
  ) AS novos_qtd,

  -- I: # Churn (*-1)
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE dt_cancelado = d.Mes_Base
     AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
  ) * -1 AS churn_qtd,

  -- K: $ Base Inicial
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE mes_base = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND (dt_cancelado IS NULL OR dt_cancelado <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
  ) AS base_inicial_valor,

  -- L: $ Novos
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao = 'Novo' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
  ) AS novos_valor,

  -- M: $ Up
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
  ) AS up_valor,

  -- N: $ Down
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
  ) AS down_valor,

  -- O: $ Churn (*-1)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
  ) * -1 AS churn_valor,

  -- Q: $ Recuperados
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao_churn = 'CHURN - Recuperado' AND mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe AND regionalizacao = d.Regiao_Macro
     AND canal_conta = d.Canal AND tamanho_ajustado_full = d.Tamanho
  ) AS recuperados_valor,

  -- R: $ Recuperados (novos)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao_churn = 'CHURN - Recuperado' AND classificacao = 'Novo'
     AND mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND canal_conta = d.Canal
     AND tamanho_ajustado_full = d.Tamanho
  ) AS recuperados_novos_valor,

  -- T: # Campanha
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE faturado_mes_campanha IS NOT NULL AND faturado_mes_campanha <> 0
     AND mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND canal_conta = d.Canal
  ) AS campanha_qtd,

  -- U: $ Campanha
  (SELECT COALESCE(SUM(faturado_mes_campanha), 0) FROM r
   WHERE mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND canal_conta = d.Canal
  ) AS campanha_valor,

  -- V: # SVA
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE ((faturado_mes_bairro_vip IS NOT NULL AND faturado_mes_bairro_vip <> 0)
       OR (faturado_mes_topo_fixo IS NOT NULL AND faturado_mes_topo_fixo <> 0))
     AND mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND canal_conta = d.Canal
  ) AS sva_qtd,

  -- W: $ SVA
  (SELECT COALESCE(SUM(COALESCE(faturado_mes_bairro_vip,0) + COALESCE(faturado_mes_topo_fixo,0)), 0) FROM r
   WHERE mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND canal_conta = d.Canal
  ) AS sva_valor,

  -- X: $ Pagamentos Adiantados
  (SELECT COALESCE(SUM(SAFE_CAST(antecipado AS FLOAT64)), 0) FROM cb
   WHERE mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND coordenador_ajustado = d.Equipe AND canal = d.Canal
     AND regionalizacao = d.Regiao_Macro AND tamanho = d.Tamanho
  ) AS pagamentos_adiantados_valor,

  -- Y: $ Pagamentos no mês
  (SELECT COALESCE(SUM(SAFE_CAST(no_mes AS FLOAT64)), 0) FROM cb
   WHERE mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND coordenador_ajustado = d.Equipe AND canal = d.Canal
     AND regionalizacao = d.Regiao_Macro AND tamanho = d.Tamanho
  ) AS pagamentos_no_mes_valor,

  -- Z: $ Pagamentos Transcorridos
  (SELECT COALESCE(SUM(SAFE_CAST(transcorrido AS FLOAT64)), 0) FROM cb
   WHERE mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND coordenador_ajustado = d.Equipe AND canal = d.Canal
     AND regionalizacao = d.Regiao_Macro AND tamanho = d.Tamanho
  ) AS pagamentos_transcorridos_valor,

  -- AA: $ Pagamento Campanha
  (SELECT COALESCE(SUM(pago_mes_campanha), 0) FROM r
   WHERE mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
  ) AS pagamento_campanha_valor,

  -- AB: $ Pagamento SVA
  (SELECT COALESCE(SUM(COALESCE(pago_mes_bairro,0) + COALESCE(pago_mes_topo,0)), 0) FROM r
   WHERE mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
  ) AS pagamento_sva_valor,

  -- AC: # Pagamentos Adiantados
  (SELECT COUNT(*) FROM cb
   WHERE SAFE_CAST(antecipado AS FLOAT64) <> 0
     AND mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND canal = d.Canal AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho = d.Tamanho
  ) AS pagamentos_adiantados_qtd,

  -- AD: # Pagamentos no mês
  (SELECT COUNT(*) FROM cb
   WHERE SAFE_CAST(no_mes AS FLOAT64) <> 0
     AND mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND coordenador_ajustado = d.Equipe AND canal = d.Canal
     AND regionalizacao = d.Regiao_Macro AND tamanho = d.Tamanho
  ) AS pagamentos_no_mes_qtd,

  -- AE: # Pagamentos Transcorridos
  (SELECT COUNT(*) FROM cb
   WHERE SAFE_CAST(transcorrido AS FLOAT64) <> 0
     AND mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND coordenador_ajustado = d.Equipe AND canal = d.Canal
     AND regionalizacao = d.Regiao_Macro AND tamanho = d.Tamanho
  ) AS pagamentos_transcorridos_qtd,

  -- AF: # Pagamento Campanha
  -- NOTA: Usa 'cordenador' (campo bruto, col AF do Sheets) intencionalmente,
  -- conforme fórmula original: SUMIFS(...;'Receita 4.0/SVA'!AF:AF;C2;...)
  (SELECT COALESCE(SUM(apoio_qtd_campanha), 0) FROM r
   WHERE mes_base = d.Mes_Base AND canal_conta = d.Canal
     AND cordenador = d.Equipe AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
  ) AS pagamento_campanha_qtd,

  -- AG: # Pagamento SVA
  -- NOTA: Usa 'cordenador' (campo bruto) — mesma razão que AF acima.
  (SELECT COALESCE(SUM(apoio_qtd_sva), 0) FROM r
   WHERE mes_base = d.Mes_Base AND canal_conta = d.Canal
     AND cordenador = d.Equipe AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
  ) AS pagamento_sva_qtd,

  -- AH: # Up
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
  ) AS up_qtd,

  -- AI: # Down
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
  ) AS down_qtd,

  -- AJ: $ Base Inicial Pago
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE mes_base = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND (dt_cancelado IS NULL OR dt_cancelado <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND status_ts = '1-Paid'
     AND canal_conta = d.Canal
  ) AS base_inicial_pago_valor,

  -- AK: $ Novos Pago
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao = 'Novo' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND status_ts = '1-Paid'
     AND canal_conta = d.Canal
  ) AS novos_pago_valor,

  -- AL: $ Up Pago
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND status_ts = '1-Paid'
     AND canal_conta = d.Canal
  ) AS up_pago_valor,

  -- AM: $ Down Pago
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND status_ts = '1-Paid'
     AND canal_conta = d.Canal
  ) AS down_pago_valor,

  -- AN: $ Churn Pago (*-1)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_ts = '1-Paid'
  ) * -1 AS churn_pago_valor,

  -- AP: $ Recuperados Pago
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao_churn = 'CHURN - Recuperado' AND mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe AND regionalizacao = d.Regiao_Macro
     AND canal_conta = d.Canal AND tamanho_ajustado_full = d.Tamanho
     AND status_ts = '1-Paid'
  ) AS recuperados_pago_valor,

  -- AQ: $ Recuperados (novos) Pago
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao_churn = 'CHURN - Recuperado' AND classificacao = 'Novo'
     AND mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND status_ts = '1-Paid' AND canal_conta = d.Canal
  ) AS recuperados_novos_pago_valor,

  -- AS: # Churn - Migração IN (*-1)
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado'
  ) * -1 AS churn_migracao_in_qtd,

  -- AT: # Up - Migração IN
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado'
  ) AS up_migracao_in_qtd,

  -- AU: # Down - Migração IN
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado'
  ) AS down_migracao_in_qtd,

  -- AV: $ Churn - Migração IN (*-1)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado'
  ) * -1 AS churn_migracao_in_valor,

  -- AW: $ Up - Migração IN
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado'
  ) AS up_migracao_in_valor,

  -- AX: $ Down - Migração IN
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado'
  ) AS down_migracao_in_valor,

  -- AY: $ Base Migração IN
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE mes_base = d.Mes_Base AND tamanho_ajustado_full = d.Tamanho
     AND regionalizacao = d.Regiao_Macro AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal AND status_migrado = 'Migrado'
  ) AS base_migracao_in_valor,

  -- AZ: # Base Migração IN
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE mes_base = d.Mes_Base AND tamanho_ajustado_full = d.Tamanho
     AND regionalizacao = d.Regiao_Macro AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal AND status_migrado = 'Migrado'
  ) AS base_migracao_in_qtd,

  -- BA: # Churn - Migração OUT (*-1) — usa coordenador_ajustado_out e aux_canal_out
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado'
  ) * -1 AS churn_migracao_out_qtd,

  -- BB: # Up - Migração OUT
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado'
  ) AS up_migracao_out_qtd,

  -- BC: # Down - Migração OUT
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado'
  ) AS down_migracao_out_qtd,

  -- BD: $ Churn - Migração OUT (*-1)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado'
  ) * -1 AS churn_migracao_out_valor,

  -- BE: $ Up - Migração OUT
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado'
  ) AS up_migracao_out_valor,

  -- BF: $ Down - Migração OUT
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado'
  ) AS down_migracao_out_valor,

  -- BG: $ Base - Migração OUT
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE mes_base = d.Mes_Base AND tamanho_ajustado_full = d.Tamanho
     AND regionalizacao = d.Regiao_Macro AND coordenador_ajustado_out = d.Equipe
     AND aux_canal_out = d.Canal AND status_migrado = 'Migrado'
  ) AS base_migracao_out_valor,

  -- BH: # Base - Migração OUT
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE mes_base = d.Mes_Base AND tamanho_ajustado_full = d.Tamanho
     AND regionalizacao = d.Regiao_Macro AND coordenador_ajustado_out = d.Equipe
     AND aux_canal_out = d.Canal AND status_migrado = 'Migrado'
  ) AS base_migracao_out_qtd

FROM dimensoes d
WHERE d.Regiao_Macro IS NOT NULL
  AND d.Equipe IS NOT NULL AND d.Equipe <> ''
ORDER BY d.Mes_Base DESC, d.Canal, d.Equipe
