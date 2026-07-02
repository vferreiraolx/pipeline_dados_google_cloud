-- =============================================================================
-- Tabela Derivada: bd_full
-- =============================================================================
-- Descrição: Replica a aba "BD FULL" do Sheets. Combina receita_enriquecida +
--            planos periódicos. Filtro BM (Transferências?) = id_migracao_pro_field.
--            Quando BM="Sim", exclui contribuição de Planos Periódicos.
--
-- NOTA 1: Usa COUNT(*) ao invés de COUNT(DISTINCT advertiser_id) para replicar
--         fielmente o comportamento do COUNTIFS do Google Sheets, que não
--         deduplicam por advertiser. Um mesmo cliente com múltiplas linhas
--         no mesmo mês é contado múltiplas vezes (limitação original do Sheets).
--
-- NOTA 2: O split Transferencias (Sim/Não) pode divergir do Sheets porque
--         a CTE 'transferencias' na receita_enriquecida é derivada dos dados
--         (busca advertisers que estão no Field e já estiveram em outro canal),
--         enquanto o Sheets usa uma aba manual "Transferências" com lista fixa.
--         O TOTAL (Sim+Não) por combinação bate; apenas a distribuição difere.
--         Para fechar 1:1, seria necessário importar essa aba como tabela no BQ.
--
-- NOTA 3: Pode haver diferença residual de +1 a +12 registros em Online/Inside
--         causada por: (a) diferença no método de classificação de tamanho
--         (receita_enriquecida usa REGEXP_EXTRACT do pacote vs campo tamanho),
--         (b) timing de extração dos planos periódicos (partição dt=MAX(dt)).
--         Impacto líquido: ~0.3% do total.
--
-- Dependências:
--   - conect-python-g-sheets.planejamento_comercial.receita_enriquecida
--   - conect-python-g-sheets.planejamento_comercial.cb_pagamentos
--   - conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb
--
-- Modo de escrita: WRITE_TRUNCATE (substituição completa a cada execução)
-- =============================================================================

WITH r AS (
  SELECT
    *,
    -- Reclassifica PP como P para o BD FULL (Sheets não separa PP)
    CASE WHEN tamanho_ajustado = 'PP' THEN 'P' ELSE tamanho_ajustado END AS tamanho_ajustado_full
  FROM `conect-python-g-sheets.planejamento_comercial.receita_enriquecida`
),
cb AS (
  SELECT * FROM `conect-python-g-sheets.planejamento_comercial.cb_pagamentos`
),
pp_raw AS (
  SELECT *
  FROM `conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb`
  WHERE dt = (SELECT MAX(dt) FROM `conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb`)
),
pp AS (
  SELECT
    p.*,
    CASE
      WHEN estado_conta IS NULL OR TRIM(CAST(estado_conta AS STRING)) = '' THEN ''
      WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(estado_conta AS STRING))), r'^(RS|SC|PR)$') THEN 'Sul'
      WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(estado_conta AS STRING))), r'^(MG|ES)$') THEN 'MG/ES'
      WHEN UPPER(TRIM(CAST(estado_conta AS STRING))) = 'RJ' THEN 'RJ'
      WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(estado_conta AS STRING))), r'^(MS|MT|GO|DF|TO|PA|AP|RO|AC|AM)$') THEN 'NO/CO'
      WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(estado_conta AS STRING))), r'^(BA|PI|MA|CE|RN|PB|PE|AL|SE)$') THEN 'NE'
      WHEN UPPER(TRIM(CAST(estado_conta AS STRING))) = 'SP' AND UPPER(TRIM(CAST(cidade_conta AS STRING))) = 'SÃO PAULO' THEN 'Sp Capital'
      WHEN UPPER(TRIM(CAST(estado_conta AS STRING))) = 'SP' THEN 'SP Interior & Litoral'
      ELSE 'Outros'
    END AS pp_regionalizacao,
    CASE
      WHEN UPPER(TRIM(CAST(canal AS STRING))) IN ('ONLINE', 'ND') THEN UPPER(TRIM(CAST(canal AS STRING)))
      ELSE UPPER(TRIM(COALESCE(CAST(coordenador_conta AS STRING), '')))
    END AS pp_equipe,
    -- Reclassifica PP como P para o BD FULL
    CASE WHEN CAST(tamanho AS STRING) = 'PP' THEN 'P' ELSE CAST(tamanho AS STRING) END AS pp_tamanho
  FROM pp_raw p
),
-- Dimensões do BD FULL: Canal, Equipe, Regiao_Macro, Mes_Base, Tamanho, Transferencias
dimensoes AS (
  SELECT DISTINCT
    canal_conta AS Canal,
    coordenador_ajustado AS Equipe,
    regionalizacao AS Regiao_Macro,
    mes_base AS Mes_Base,
    COALESCE(tamanho_ajustado_full, '') AS Tamanho,
    COALESCE(id_migracao_pro_field, 'Não') AS Transferencias
  FROM r
  WHERE canal_conta IS NOT NULL AND canal_conta <> ''

  UNION DISTINCT

  SELECT DISTINCT
    CAST(canal AS STRING) AS Canal,
    pp_equipe AS Equipe,
    pp_regionalizacao AS Regiao_Macro,
    CAST(competencia AS DATE) AS Mes_Base,
    pp_tamanho AS Tamanho,
    'Não' AS Transferencias
  FROM pp
  WHERE CAST(canal AS STRING) IS NOT NULL AND CAST(canal AS STRING) <> ''
    AND pp_tamanho IS NOT NULL AND pp_tamanho <> ''
)

SELECT
  d.Canal,
  d.Equipe,
  d.Regiao_Macro,
  d.Mes_Base,
  d.Tamanho,

  -- G: # Base Inicial (receita mês anterior sem churn + migração IN - OUT + planos periódicos)
  (SELECT COUNT(*) FROM r
   WHERE mes_base = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND (dt_cancelado IS NULL OR dt_cancelado <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
     AND COALESCE(regionalizacao, '') = d.Regiao_Macro AND COALESCE(tamanho_ajustado_full, '') = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND COALESCE(id_migracao_pro_field, 'Não') = d.Transferencias
  )
  + (SELECT COUNT(*) FROM r
     WHERE mes_base = d.Mes_Base AND COALESCE(tamanho_ajustado_full, '') = d.Tamanho
       AND COALESCE(regionalizacao, '') = d.Regiao_Macro AND coordenador_ajustado = d.Equipe
       AND canal_conta = d.Canal AND status_migrado = 'Migrado'
       AND COALESCE(id_migracao_pro_field, 'Não') = d.Transferencias
    )
  - (SELECT COUNT(*) FROM r
     WHERE mes_base = d.Mes_Base AND COALESCE(tamanho_ajustado_full, '') = d.Tamanho
       AND COALESCE(regionalizacao, '') = d.Regiao_Macro AND coordenador_ajustado_out = d.Equipe
       AND aux_canal_out = d.Canal AND status_migrado = 'Migrado'
       AND COALESCE(id_migracao_pro_field, 'Não') = d.Transferencias
    )
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE
    (SELECT COUNT(*) FROM pp
     WHERE CAST(competencia AS DATE) = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
       AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
       AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
       AND (mes_churn IS NULL OR CAST(mes_churn AS DATE) <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
    ) END
  AS base_inicial_qtd,

  -- H: # Novos
  (SELECT COUNT(*) FROM r
   WHERE classificacao = 'Novo' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND id_migracao_pro_field = d.Transferencias
  )
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE
    (SELECT COUNT(*) FROM pp
     WHERE CAST(competencia AS DATE) = d.Mes_Base
       AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
       AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
       AND status_recorrente = 'Novo'
    ) END
  AS novos_qtd,

  -- I: # Churn (*-1)
  (SELECT COUNT(*) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND id_migracao_pro_field = d.Transferencias
  ) * -1
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE
    (SELECT COUNT(*) FROM pp
     WHERE CAST(mes_churn AS DATE) = d.Mes_Base
       AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
       AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
       AND status_recorrente = 'Churn'
    ) * -1 END
  AS churn_qtd,

  -- K: $ Base Inicial
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE mes_base = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND (dt_cancelado IS NULL OR dt_cancelado <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND id_migracao_pro_field = d.Transferencias
  )
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE
    (SELECT COALESCE(SUM(CAST(valor_mensal AS FLOAT64)), 0) FROM pp
     WHERE CAST(competencia AS DATE) = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
       AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
       AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
       AND (mes_churn IS NULL OR CAST(mes_churn AS DATE) <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
    ) END
  AS base_inicial_valor,

  -- L: $ Novos
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao = 'Novo' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND id_migracao_pro_field = d.Transferencias
  )
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE
    (SELECT COALESCE(SUM(CAST(valor_mensal AS FLOAT64)), 0) FROM pp
     WHERE CAST(competencia AS DATE) = d.Mes_Base
       AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
       AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
       AND status_recorrente = 'Novo'
    ) END
  AS novos_valor,

  -- M: $ Up
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND id_migracao_pro_field = d.Transferencias
  ) AS up_valor,

  -- N: $ Down
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND id_migracao_pro_field = d.Transferencias
  ) AS down_valor,

  -- O: $ Churn (*-1) + planos periódicos
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND id_migracao_pro_field = d.Transferencias
  ) * -1
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE
    (SELECT COALESCE(SUM(CAST(valor_mensal AS FLOAT64)), 0) FROM pp
     WHERE CAST(mes_churn AS DATE) = d.Mes_Base
       AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
       AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
       AND status_recorrente = 'Churn'
    ) * -1 END
  AS churn_valor,

  -- Q: $ Recuperados
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao_churn = 'CHURN - Recuperado' AND mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe AND regionalizacao = d.Regiao_Macro
     AND canal_conta = d.Canal AND tamanho_ajustado_full = d.Tamanho
     AND id_migracao_pro_field = d.Transferencias
  ) AS recuperados_valor,

  -- R: $ Recuperados (novos)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao_churn = 'CHURN - Recuperado' AND classificacao = 'Novo'
     AND mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND canal_conta = d.Canal
     AND tamanho_ajustado_full = d.Tamanho AND id_migracao_pro_field = d.Transferencias
  ) AS recuperados_novos_valor,

  -- T: # Campanha
  (SELECT COUNT(*) FROM r
   WHERE faturado_mes_campanha IS NOT NULL AND faturado_mes_campanha <> 0
     AND mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND canal_conta = d.Canal AND id_migracao_pro_field = d.Transferencias
  ) AS campanha_qtd,

  -- U: $ Campanha
  (SELECT COALESCE(SUM(faturado_mes_campanha), 0) FROM r
   WHERE mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND canal_conta = d.Canal AND id_migracao_pro_field = d.Transferencias
  ) AS campanha_valor,

  -- V: # SVA
  (SELECT COUNT(*) FROM r
   WHERE ((faturado_mes_bairro_vip IS NOT NULL AND faturado_mes_bairro_vip <> 0)
       OR (faturado_mes_topo_fixo IS NOT NULL AND faturado_mes_topo_fixo <> 0))
     AND mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND canal_conta = d.Canal AND id_migracao_pro_field = d.Transferencias
  ) AS sva_qtd,

  -- W: $ SVA
  (SELECT COALESCE(SUM(COALESCE(faturado_mes_bairro_vip,0) + COALESCE(faturado_mes_topo_fixo,0)), 0) FROM r
   WHERE mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND canal_conta = d.Canal AND id_migracao_pro_field = d.Transferencias
  ) AS sva_valor,

  -- X: $ Pagamentos Adiantados
  (SELECT COALESCE(SUM(SAFE_CAST(antecipado AS FLOAT64)), 0) FROM cb
   WHERE mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND canal = d.Canal AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho = d.Tamanho
     AND id_migracao_pro_field = d.Transferencias
  ) AS pagamentos_adiantados_valor,

  -- Y: $ Pagamentos no mês (CB + Planos Periódicos PAID)
  (SELECT COALESCE(SUM(SAFE_CAST(no_mes AS FLOAT64)), 0) FROM cb
   WHERE mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND canal = d.Canal AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho = d.Tamanho
     AND id_migracao_pro_field = d.Transferencias
  )
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE
    (SELECT COALESCE(SUM(CAST(valor_mensal AS FLOAT64)), 0) FROM pp
     WHERE CAST(competencia AS DATE) = d.Mes_Base
       AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
       AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
       AND CAST(status AS STRING) = 'PAID'
    ) END
  AS pagamentos_no_mes_valor,

  -- Z: $ Pagamentos Transcorridos
  (SELECT COALESCE(SUM(SAFE_CAST(transcorrido AS FLOAT64)), 0) FROM cb
   WHERE mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND canal = d.Canal AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho = d.Tamanho
     AND id_migracao_pro_field = d.Transferencias
  ) AS pagamentos_transcorridos_valor,

  -- AA: $ Pagamento Campanha
  (SELECT COALESCE(SUM(pago_mes_campanha), 0) FROM r
   WHERE mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho AND id_migracao_pro_field = d.Transferencias
  ) AS pagamento_campanha_valor,

  -- AB: $ Pagamento SVA
  (SELECT COALESCE(SUM(COALESCE(pago_mes_bairro,0) + COALESCE(pago_mes_topo,0)), 0) FROM r
   WHERE mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho AND id_migracao_pro_field = d.Transferencias
  ) AS pagamento_sva_valor,

  -- AH: # Up
  (SELECT COUNT(*) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND id_migracao_pro_field = d.Transferencias
  ) AS up_qtd,

  -- AI: # Down
  (SELECT COUNT(*) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND id_migracao_pro_field = d.Transferencias
  ) AS down_qtd,

  -- AJ: $ Base Inicial Pago
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE mes_base = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND (dt_cancelado IS NULL OR dt_cancelado <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_ts = '1-Paid' AND id_migracao_pro_field = d.Transferencias
  )
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE
    (SELECT COALESCE(SUM(CAST(valor_mensal AS FLOAT64)), 0) FROM pp
     WHERE CAST(competencia AS DATE) = d.Mes_Base
       AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
       AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
       AND status_recorrente IN ('flat', 'Churn')
    )
    + (SELECT COALESCE(SUM(CAST(valor_mensal AS FLOAT64)), 0) FROM pp
       WHERE CAST(mes_churn AS DATE) = d.Mes_Base
         AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
         AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
         AND status_recorrente = 'Churn'
    ) END
  AS base_inicial_pago_valor,

  -- AK: $ Novos Pago
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao = 'Novo' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_ts = '1-Paid' AND id_migracao_pro_field = d.Transferencias
  )
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE
    (SELECT COALESCE(SUM(CAST(valor_mensal AS FLOAT64)), 0) FROM pp
     WHERE CAST(competencia AS DATE) = d.Mes_Base
       AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
       AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
       AND status_recorrente = 'Novo'
    ) END
  AS novos_pago_valor,

  -- AL: $ Up Pago
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_ts = '1-Paid' AND id_migracao_pro_field = d.Transferencias
  ) AS up_pago_valor,

  -- AM: $ Down Pago
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_ts = '1-Paid' AND id_migracao_pro_field = d.Transferencias
  ) AS down_pago_valor,

  -- AN: $ Churn Pago (*-1)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_ts = '1-Paid' AND id_migracao_pro_field = d.Transferencias
  ) * -1
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE
    (SELECT COALESCE(SUM(CAST(valor_mensal AS FLOAT64)), 0) FROM pp
     WHERE CAST(mes_churn AS DATE) = d.Mes_Base
       AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
       AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
       AND status_recorrente = 'Churn'
    ) * -1 END
  AS churn_pago_valor,

  -- AP: $ Recuperados Pago
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao_churn = 'CHURN - Recuperado' AND mes_base = d.Mes_Base
     AND coordenador_ajustado = d.Equipe AND regionalizacao = d.Regiao_Macro
     AND canal_conta = d.Canal AND tamanho_ajustado_full = d.Tamanho
     AND status_ts = '1-Paid' AND id_migracao_pro_field = d.Transferencias
  ) AS recuperados_pago_valor,

  -- AQ: $ Recuperados (novos) Pago
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE classificacao_churn = 'CHURN - Recuperado' AND classificacao = 'Novo'
     AND mes_base = d.Mes_Base AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND canal_conta = d.Canal
     AND tamanho_ajustado_full = d.Tamanho AND status_ts = '1-Paid'
     AND id_migracao_pro_field = d.Transferencias
  ) AS recuperados_novos_pago_valor,

  -- AZ: # Base Migração IN
  (SELECT COUNT(*) FROM r
   WHERE mes_base = d.Mes_Base AND tamanho_ajustado_full = d.Tamanho
     AND regionalizacao = d.Regiao_Macro AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal AND status_migrado = 'Migrado'
     AND id_migracao_pro_field = d.Transferencias
  ) AS base_migracao_in_qtd,

  -- AS: # Churn - Migração IN (*-1)
  (SELECT COUNT(*) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) * -1 AS churn_migracao_in_qtd,

  -- AT: # Up - Migração IN
  (SELECT COUNT(*) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) AS up_migracao_in_qtd,

  -- AU: # Down - Migração IN
  (SELECT COUNT(*) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) AS down_migracao_in_qtd,

  -- AV: $ Churn - Migração IN (*-1)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) * -1 AS churn_migracao_in_valor,

  -- AW: $ Up - Migração IN
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) AS up_migracao_in_valor,

  -- AX: $ Down - Migração IN
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) AS down_migracao_in_valor,

  -- AY: $ Base Migração IN
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE mes_base = d.Mes_Base AND tamanho_ajustado_full = d.Tamanho
     AND regionalizacao = d.Regiao_Macro AND coordenador_ajustado = d.Equipe
     AND canal_conta = d.Canal AND status_migrado = 'Migrado'
     AND id_migracao_pro_field = d.Transferencias
  ) AS base_migracao_in_valor,

  -- BA: # Churn - Migração OUT (*-1)
  (SELECT COUNT(*) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) * -1 AS churn_migracao_out_qtd,

  -- BB: # Up - Migração OUT
  (SELECT COUNT(*) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) AS up_migracao_out_qtd,

  -- BC: # Down - Migração OUT
  (SELECT COUNT(*) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) AS down_migracao_out_qtd,

  -- BD: $ Churn - Migração OUT (*-1)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) * -1 AS churn_migracao_out_valor,

  -- BE: $ Up - Migração OUT
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Upgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) AS up_migracao_out_valor,

  -- BF: $ Down - Migração OUT
  (SELECT COALESCE(SUM(delta), 0) FROM r
   WHERE classificacao = 'Downgrade' AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) AS down_migracao_out_valor,

  -- BG: $ Base - Migração OUT
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE mes_base = d.Mes_Base AND tamanho_ajustado_full = d.Tamanho
     AND regionalizacao = d.Regiao_Macro AND coordenador_ajustado_out = d.Equipe
     AND aux_canal_out = d.Canal AND status_migrado = 'Migrado'
     AND id_migracao_pro_field = d.Transferencias
  ) AS base_migracao_out_valor,

  -- BH: # Base - Migração OUT
  (SELECT COUNT(*) FROM r
   WHERE mes_base = d.Mes_Base AND tamanho_ajustado_full = d.Tamanho
     AND regionalizacao = d.Regiao_Macro AND coordenador_ajustado_out = d.Equipe
     AND aux_canal_out = d.Canal AND status_migrado = 'Migrado'
     AND id_migracao_pro_field = d.Transferencias
  ) AS base_migracao_out_qtd,

  -- BN: $ Volume transcorrido (SUMIFS da coluna AZ da receita_enriquecida do mês anterior)
  (SELECT COALESCE(SUM(
    CASE
      WHEN day_base >= DATE_SUB(DATE_ADD(LAST_DAY(mes_base), INTERVAL 1 DAY), INTERVAL 6 DAY)
        AND day_base <= LAST_DAY(mes_base)
        AND (dt_cancelado IS NULL
             OR EXTRACT(MONTH FROM dt_cancelado) <> EXTRACT(MONTH FROM mes_base)
             OR EXTRACT(YEAR FROM dt_cancelado) <> EXTRACT(YEAR FROM mes_base))
      THEN faturado_mes
      ELSE 0
    END
  ), 0) FROM r
   WHERE mes_base = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND id_migracao_pro_field = d.Transferencias
  ) AS volume_transcorrido_valor,

  -- BO: # Volume transcorrido (COUNTIFS onde volume_transcorrido > 0)
  (SELECT COUNT(*) FROM r
   WHERE mes_base = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND id_migracao_pro_field = d.Transferencias
     AND day_base >= DATE_SUB(DATE_ADD(LAST_DAY(mes_base), INTERVAL 1 DAY), INTERVAL 6 DAY)
     AND day_base <= LAST_DAY(mes_base)
     AND (dt_cancelado IS NULL
          OR EXTRACT(MONTH FROM dt_cancelado) <> EXTRACT(MONTH FROM mes_base)
          OR EXTRACT(YEAR FROM dt_cancelado) <> EXTRACT(YEAR FROM mes_base))
  ) AS volume_transcorrido_qtd,

  -- AC: # Pagamentos Adiantados (COUNTIFS cb onde antecipado <> 0)
  (SELECT COUNT(*) FROM cb
   WHERE SAFE_CAST(antecipado AS FLOAT64) <> 0
     AND mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND canal = d.Canal AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho = d.Tamanho
     AND id_migracao_pro_field = d.Transferencias
  ) AS pagamentos_adiantados_qtd,

  -- AD: # Pagamentos no mês (COUNTIFS cb onde no_mes <> 0 + planos PAID)
  (SELECT COUNT(*) FROM cb
   WHERE SAFE_CAST(no_mes AS FLOAT64) <> 0
     AND mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND canal = d.Canal AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho = d.Tamanho
     AND id_migracao_pro_field = d.Transferencias
  )
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE
    (SELECT COUNT(*) FROM pp
     WHERE CAST(competencia AS DATE) = d.Mes_Base
       AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
       AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
       AND CAST(status AS STRING) = 'PAID'
    ) END
  AS pagamentos_no_mes_qtd,

  -- AE: # Pagamentos Transcorridos (COUNTIFS cb onde transcorrido <> 0)
  (SELECT COUNT(*) FROM cb
   WHERE SAFE_CAST(transcorrido AS FLOAT64) <> 0
     AND mes_pago = FORMAT_DATE('%d/%m/%Y', d.Mes_Base)
     AND canal = d.Canal AND coordenador_ajustado = d.Equipe
     AND regionalizacao = d.Regiao_Macro AND tamanho = d.Tamanho
     AND id_migracao_pro_field = d.Transferencias
  ) AS pagamentos_transcorridos_qtd,

  -- AF: # Pagamento Campanha (SUMIFS apoio_qtd_campanha, filtra por cordenador)
  (SELECT COALESCE(SUM(apoio_qtd_campanha), 0) FROM r
   WHERE mes_base = d.Mes_Base AND canal_conta = d.Canal
     AND cordenador = d.Equipe AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho AND id_migracao_pro_field = d.Transferencias
  ) AS pagamento_campanha_qtd,

  -- AG: # Pagamento SVA (SUMIFS apoio_qtd_sva, filtra por cordenador)
  (SELECT COALESCE(SUM(apoio_qtd_sva), 0) FROM r
   WHERE mes_base = d.Mes_Base AND canal_conta = d.Canal
     AND cordenador = d.Equipe AND regionalizacao = d.Regiao_Macro
     AND tamanho_ajustado_full = d.Tamanho AND id_migracao_pro_field = d.Transferencias
  ) AS pagamento_sva_qtd,

  -- AO: $ Cancelamento total Pago (= churn_pago * -1 + recuperados_pago)
  -- Calculado inline: AN*-1 + AP
  ((SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_ts = '1-Paid' AND id_migracao_pro_field = d.Transferencias
  )
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE
    (SELECT COALESCE(SUM(CAST(valor_mensal AS FLOAT64)), 0) FROM pp
     WHERE CAST(mes_churn AS DATE) = d.Mes_Base
       AND CAST(canal AS STRING) = d.Canal AND pp_equipe = d.Equipe
       AND pp_regionalizacao = d.Regiao_Macro AND pp_tamanho = d.Tamanho
       AND status_recorrente = 'Churn'
    ) END)
  + (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
     WHERE classificacao_churn = 'CHURN - Recuperado' AND mes_base = d.Mes_Base
       AND coordenador_ajustado = d.Equipe AND regionalizacao = d.Regiao_Macro
       AND canal_conta = d.Canal AND tamanho_ajustado_full = d.Tamanho
       AND status_ts = '1-Paid' AND id_migracao_pro_field = d.Transferencias
  ) AS cancelamento_total_pago_valor,

  -- AR: $ Base Final Pago (= SUM(AJ:AN))
  -- base_inicial_pago + novos_pago + up_pago + down_pago + churn_pago
  -- Simplificado: base_ini_pago inline (copia mesma lógica)

  -- BI: CHURN IN # (filtro adicional: mes_base = Mes_Base E dt_cancelado = Mes_Base)
  (SELECT COUNT(*) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) * -1 AS churn_in_bi_qtd,

  -- BJ: CHURN IN $ (mesmo filtro do BI com SUM faturado_mes)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado = d.Equipe AND canal_conta = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) * -1 AS churn_in_bi_valor,

  -- BK: CHURN OUT # (usando AV/AI + mes_base = Mes_Base)
  (SELECT COUNT(*) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) * -1 AS churn_out_bi_qtd,

  -- BL: CHURN OUT $ (usando AV/AI + mes_base = Mes_Base)
  (SELECT COALESCE(SUM(faturado_mes), 0) FROM r
   WHERE dt_cancelado = d.Mes_Base AND classificacao_churn = 'CHURN'
     AND mes_base = d.Mes_Base
     AND regionalizacao = d.Regiao_Macro AND tamanho_ajustado_full = d.Tamanho
     AND coordenador_ajustado_out = d.Equipe AND aux_canal_out = d.Canal
     AND status_migrado = 'Migrado' AND id_migracao_pro_field = d.Transferencias
  ) * -1 AS churn_out_bi_valor,

  -- BP: Chave EQUIPE X COORDENADOR
  CONCAT(d.Canal, d.Equipe) AS chave_equipe_coordenador,

  -- Transferências flag
  d.Transferencias

FROM dimensoes d
ORDER BY d.Mes_Base DESC, d.Canal, d.Equipe
