-- =============================================================================
-- Tabela Derivada: bd_planos_uf
-- =============================================================================
-- Descrição: Replica a aba "BD Planos_UF" do Sheets - agregações por
--            Canal, Equipe, Regiao_Macro, Mes Base, Tamanho, UF.
--            Usa receita_enriquecida + cb_pagamentos como fontes.
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
-- Gerar dimensões distintas a partir da receita enriquecida
dimensoes AS (
  SELECT DISTINCT
    canal_conta AS Canal,
    coordenador_ajustado AS Equipe,
    regionalizacao AS Regiao_Macro,
    mes_base AS Mes_Base,
    tamanho_ajustado_full AS Tamanho,
    estado AS UF
  FROM r
  WHERE canal_conta IS NOT NULL AND canal_conta <> ''
)

SELECT
  d.Canal,
  d.Equipe,
  d.Regiao_Macro,
  d.Mes_Base,
  d.Tamanho,
  d.UF,

  -- H: # Base Inicial (COUNTIFS mes_base = EDATE(Mes_Base,-1) AND dt_cancelado <> EDATE(Mes_Base,-1) AND dt_cancelado IS NULL)
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE mes_base = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND (dt_cancelado IS NULL OR dt_cancelado <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS base_inicial_qtd,

  -- I: # Novos
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE classificacao = 'Novo'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS novos_qtd,

  -- J: # Churn (*-1)
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE dt_cancelado = d.Mes_Base
     AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) * -1 AS churn_qtd,

  -- L: $ Base Inicial (SUMIFS faturado_mes do mês anterior, dt_cancelado <> mês anterior)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE mes_base = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND (dt_cancelado IS NULL OR dt_cancelado <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS base_inicial_valor,

  -- M: $ Novos
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao = 'Novo'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS novos_valor,

  -- N: $ Up
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Upgrade'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS up_valor,

  -- O: $ Down
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Downgrade'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS down_valor,

  -- P: $ Churn (*-1)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base
     AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) * -1 AS churn_valor,

  -- R: $ Recuperados
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao_churn = 'CHURN - Recuperado'
     AND mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND canal_conta = d.Canal
     AND tamanho_ajustado_full = d.Tamanho
     AND estado = d.UF
  ) AS recuperados_valor,

  -- S: $ Recuperados (novos)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao_churn = 'CHURN - Recuperado'
     AND classificacao = 'Novo'
     AND mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND canal_conta = d.Canal
     AND tamanho_ajustado_full = d.Tamanho
     AND estado = d.UF
  ) AS recuperados_novos_valor,

  -- U: # Campanha
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE faturado_mes_campanha IS NOT NULL AND faturado_mes_campanha <> 0
     AND mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS campanha_qtd,

  -- V: $ Campanha
  (SELECT COALESCE(SUM(faturado_mes_campanha), 0) FROM r
   WHERE mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS campanha_valor,

  -- W: # SVA (bairro_vip OU topo_fixo com valor)
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE ((faturado_mes_bairro_vip IS NOT NULL AND faturado_mes_bairro_vip <> 0)
       OR (faturado_mes_topo_fixo IS NOT NULL AND faturado_mes_topo_fixo <> 0))
     AND mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS sva_qtd,

  -- X: $ SVA (bairro_vip + topo_fixo)
  (SELECT COALESCE(SUM(COALESCE(faturado_mes_bairro_vip, 0) + COALESCE(faturado_mes_topo_fixo, 0)), 0) FROM r
   WHERE mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS sva_valor,

  -- Y: $ Pagamentos Adiantados (de cb_pagamentos)
  (SELECT COALESCE(SUM(SAFE_CAST(antecipado AS FLOAT64)), 0) FROM cb
   WHERE mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND coordenador_ajustado = d.Equipe
     AND canal = d.Canal
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND uf = d.UF
  ) AS pagamentos_adiantados_valor,

  -- Z: $ Pagamentos no mês
  (SELECT COALESCE(SUM(SAFE_CAST(no_mes AS FLOAT64)), 0) FROM cb
   WHERE mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND coordenador_ajustado = d.Equipe
     AND canal = d.Canal
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND uf = d.UF
  ) AS pagamentos_no_mes_valor,

  -- AA: $ Pagamentos Transcorridos
  (SELECT COALESCE(SUM(SAFE_CAST(transcorrido AS FLOAT64)), 0) FROM cb
   WHERE mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND coordenador_ajustado = d.Equipe
     AND canal = d.Canal
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND uf = d.UF
  ) AS pagamentos_transcorridos_valor,

  -- AB: $ Pagamento Campanha (pago_mes_campanha de receita)
  (SELECT COALESCE(SUM(pago_mes_campanha), 0) FROM r
   WHERE mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND estado = d.UF
  ) AS pagamento_campanha_valor,

  -- AC: $ Pagamento SVA (pago_mes_bairro + pago_mes_topo)
  (SELECT COALESCE(SUM(COALESCE(pago_mes_bairro, 0) + COALESCE(pago_mes_topo, 0)), 0) FROM r
   WHERE mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND estado = d.UF
  ) AS pagamento_sva_valor,

  -- AD: # Pagamentos Adiantados (count onde antecipado <> 0)
  (SELECT COUNT(*) FROM cb
   WHERE SAFE_CAST(antecipado AS FLOAT64) <> 0
     AND mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND canal = d.Canal
     AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND uf = d.UF
  ) AS pagamentos_adiantados_qtd,

  -- AE: # Pagamentos no mês
  (SELECT COUNT(*) FROM cb
   WHERE SAFE_CAST(no_mes AS FLOAT64) <> 0
     AND mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND coordenador_ajustado = d.Equipe
     AND canal = d.Canal
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND uf = d.UF
  ) AS pagamentos_no_mes_qtd,

  -- AF: # Pagamentos Transcorridos
  (SELECT COUNT(*) FROM cb
   WHERE SAFE_CAST(transcorrido AS FLOAT64) <> 0
     AND mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND coordenador_ajustado = d.Equipe
     AND canal = d.Canal
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND uf = d.UF
  ) AS pagamentos_transcorridos_qtd,

  -- AG: # Pagamento Campanha (apoio_qtd_campanha)
  (SELECT COALESCE(SUM(apoio_qtd_campanha), 0) FROM r
   WHERE mes_base = d.Mes_Base
     AND canal_conta = d.Canal
     AND cordenador = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND estado = d.UF
  ) AS pagamento_campanha_qtd,

  -- AH: # Pagamento SVA (apoio_qtd_sva)
  (SELECT COALESCE(SUM(apoio_qtd_sva), 0) FROM r
   WHERE mes_base = d.Mes_Base
     AND canal_conta = d.Canal
     AND cordenador = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND estado = d.UF
  ) AS pagamento_sva_qtd,

  -- AI: # Up
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE classificacao = 'Upgrade'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS up_qtd,

  -- AJ: # Down
  (SELECT COUNT(DISTINCT advertiser_id) FROM r
   WHERE classificacao = 'Downgrade'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS down_qtd,

  -- AK: $ Base Inicial Pago (status_ts = '1-Paid')
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE mes_base = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND (dt_cancelado IS NULL OR dt_cancelado <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND status_ts = '1-Paid'
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS base_inicial_pago_valor,

  -- AL: $ Novos Pago
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao = 'Novo'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND status_ts = '1-Paid'
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS novos_pago_valor,

  -- AM: $ Up Pago
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Upgrade'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND status_ts = '1-Paid'
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS up_pago_valor,

  -- AN: $ Down Pago
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Downgrade'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND status_ts = '1-Paid'
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS down_pago_valor,

  -- AO: $ Churn Pago (*-1)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base
     AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal
     AND status_ts = '1-Paid'
     AND estado = d.UF
  ) * -1 AS churn_pago_valor,

  -- AQ: $ Recuperados Pago
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao_churn = 'CHURN - Recuperado'
     AND mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND canal_conta = d.Canal
     AND tamanho_ajustado_full = d.Tamanho
     AND status_ts = '1-Paid'
     AND estado = d.UF
  ) AS recuperados_pago_valor,

  -- AR: $ Recuperados (novos) Pago
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao_churn = 'CHURN - Recuperado'
     AND classificacao = 'Novo'
     AND mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho
     AND status_ts = '1-Paid'
     AND canal_conta = d.Canal
     AND estado = d.UF
  ) AS recuperados_novos_pago_valor,

  -- AU: Chave EQUIPE X COORDENADOR
  CONCAT(d.Canal, d.Equipe) AS chave_equipe_coordenador

FROM dimensoes d
WHERE d.Regiao_Macro IS NOT NULL
  AND d.Equipe IS NOT NULL AND d.Equipe <> ''
  AND d.UF IS NOT NULL AND d.UF <> ''
ORDER BY d.Mes_Base DESC, d.Canal, d.Equipe, d.UF
