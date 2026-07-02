-- =============================================================================
-- Tabela Derivada: bd_full (v2 - OTIMIZADA com JOINs pré-agregados)
-- =============================================================================
-- Mesma lógica da v1, porém usando CTEs GROUP BY + LEFT JOIN
-- em vez de subqueries correlacionadas. De ~40min cai pra ~1-2min.
-- Refazer a tabela CB_PAGAMENTOS
-- Ajustar Pagamentos Transcorridos
-- Ajustar Pagamentos
-- =============================================================================
CREATE OR REPLACE TABLE `planejamento_comercial.teste_bd_full` AS
SELECT *, 
base_inicial_pago_valor + novos_pago_valor + up_pago_valor + down_pago_valor+churn_pago_valor AS base_final_pago_valor,
(base_inicial_qtd + novos_qtd + churn_qtd + base_migracao_in_qtd - base_migracao_out_qtd) AS base_final_qtd,
(churn_valor + recuperados_valor) AS cancelamento_total_valor,
(churn_pago_valor * -1 + recuperados_pago_valor) AS cancelamento_total_pago_valor


FROM (WITH r AS (
  SELECT *,
    CASE WHEN tamanho_ajustado = 'PP' THEN 'P' ELSE tamanho_ajustado END AS tam,
    COALESCE(regionalizacao, '') AS reg,
    COALESCE(id_migracao_pro_field, 'Não') AS transf
  FROM `conect-python-g-sheets.planejamento_comercial.receita_enriquecida`
),
cb AS (
  SELECT * FROM `conect-python-g-sheets.planejamento_comercial.cb_pagamentos`
),
pp_raw AS (
  SELECT * FROM `conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb`
  WHERE dt = (SELECT MAX(dt) FROM `conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb`)
),
/*pp_raw AS (
  SELECT * FROM (
    SELECT *,
      ROW_NUMBER() OVER (PARTITION BY id_conta_olx, id_contrato, competencia ORDER BY d_inicio DESC) AS rn
    FROM `conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb`
    WHERE dt = (SELECT MAX(dt) FROM `conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb`)
  )
  WHERE rn = 1
),*/
pp AS (
  SELECT p.*,
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
    END AS pp_reg,
    CASE WHEN UPPER(TRIM(CAST(canal AS STRING))) IN ('ONLINE','ND') THEN UPPER(TRIM(CAST(canal AS STRING)))
         ELSE UPPER(TRIM(COALESCE(CAST((coordenador_conta) AS STRING), ''))) END AS pp_eq,
    CASE WHEN CAST(tamanho AS STRING) = 'PP' THEN 'P' ELSE CAST(tamanho AS STRING) END AS pp_tam
  FROM pp_raw p
),

/*dimensoes AS (
  SELECT DISTINCT
    canal_conta AS Canal, coordenador_ajustado AS Equipe, reg AS Regiao_Macro,
    mes_base AS Mes_Base, COALESCE(tam, '') AS Tamanho, transf AS Transferencias
  FROM r WHERE canal_conta IS NOT NULL AND canal_conta <> ''
  UNION DISTINCT
  SELECT DISTINCT
    CAST(canal AS STRING), pp_eq, pp_reg, CAST(competencia AS DATE), pp_tam, 'Não'
  FROM pp WHERE CAST(canal AS STRING) IS NOT NULL AND CAST(canal AS STRING) <> ''
    AND pp_tam IS NOT NULL --AND pp_tam <> ''
),
*/
dimensoes AS (
  -- 1. Garante a cadeira de quem teve faturamento no mês ATUAL
  SELECT DISTINCT
    canal_conta AS Canal, TRIM(coordenador_ajustado,'') AS Equipe, reg AS Regiao_Macro,
    mes_base AS Mes_Base, COALESCE(tam, '') AS Tamanho, transf AS Transferencias
  FROM r WHERE canal_conta IS NOT NULL AND canal_conta <> ''

  UNION DISTINCT

  -- 2. Garante a cadeira de quem veio do mês PASSADO (Gera a Base Inicial do Antonio Gleison!)
  SELECT DISTINCT
    canal_conta AS Canal, coordenador_ajustado AS Equipe, reg AS Regiao_Macro,
    DATE_ADD(mes_base, INTERVAL 1 MONTH) AS Mes_Base, COALESCE(tam, '') AS Tamanho, transf AS Transferencias
  FROM r WHERE canal_conta IS NOT NULL AND canal_conta <> ''

  UNION DISTINCT

  -- 3. Garante a cadeira de quem teve Churn mapeado no mês corrente
  SELECT DISTINCT
    canal_conta AS Canal, coordenador_ajustado AS Equipe, reg AS Regiao_Macro,
    dt_cancelado AS Mes_Base, COALESCE(tam, '') AS Tamanho, transf AS Transferencias
  FROM r WHERE canal_conta IS NOT NULL AND canal_conta <> '' AND dt_cancelado IS NOT NULL

  UNION DISTINCT

  -- 4. Garante a grade dos Planos Periódicos
  SELECT DISTINCT
    CAST(canal AS STRING) AS Canal, pp_eq AS Equipe, pp_reg AS Regiao_Macro,
    CAST(competencia AS DATE) AS Mes_Base, pp_tam AS Tamanho, 'Não' AS Transferencias
  FROM pp WHERE CAST(canal AS STRING) IS NOT NULL AND CAST(canal AS STRING) <> ''
  UNION DISTINCT
  
  SELECT DISTINCT
    CAST(canal AS STRING) AS Canal, pp_eq AS Equipe, pp_reg AS Regiao_Macro,
    DATE_ADD(CAST(competencia AS DATE), INTERVAL 1 MONTH) AS Mes_Base, pp_tam AS Tamanho, 'Não' AS Transferencias
  FROM pp WHERE CAST(canal AS STRING) IS NOT NULL AND CAST(canal AS STRING) <> ''

  UNION DISTINCT

  SELECT DISTINCT
    aux_canal_out AS Canal, coordenador_ajustado_out AS Equipe, reg AS Regiao_Macro,
    mes_base AS Mes_Base, COALESCE(tam, '') AS Tamanho, transf AS Transferencias
  FROM r WHERE status_migrado = 'Migrado'
)
-- ===== MÉTRICAS PRÉ-AGREGADAS (cada uma escaneia r/pp/cb UMA VEZ) =====

-- G: # Base Inicial (mês anterior, sem churn no mês anterior)
,m_base_ini_qtd AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         DATE_ADD(mes_base, INTERVAL 1 MONTH) AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS val
  FROM r WHERE (dt_cancelado IS NULL OR dt_cancelado <> mes_base) --and coalesce(faturado_mes,0) > 0
  GROUP BY 1,2,3,4,5,6
),
-- G: migração IN (mes_base = Mes_Base, status_migrado = Migrado)
m_mig_in_qtd AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS val
  FROM r WHERE status_migrado = 'Migrado'
  GROUP BY 1,2,3,4,5,6
),
-- G: migração OUT
m_mig_out_qtd AS (
  SELECT aux_canal_out AS c, coordenador_ajustado_out AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t,
         COUNT(*) AS val
  FROM r WHERE status_migrado = 'Migrado'
  GROUP BY 1,2,3,4,5
),
-- G: planos periódicos base ini
m_pp_base_ini AS (
  SELECT CAST(canal AS STRING) AS c, pp_eq AS e, pp_reg AS rg,
         DATE_ADD(CAST(competencia AS DATE), INTERVAL 1 MONTH) AS mes_ref, pp_tam AS t,
         COUNT(*) AS val
  FROM pp WHERE (mes_churn IS NULL OR CAST(mes_churn AS DATE) <> CAST(competencia AS DATE))
  AND (
      CAST(canal AS STRING) NOT IN ('Online', 'ND')
      OR COALESCE(CAST(coordenador_conta AS STRING), '') = ''
    ) --AND CAST(valor_mensal AS FLOAT64) > 0 
  GROUP BY 1,2,3,4,5
),

-- H: # Novos
m_novos_qtd AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS val
  FROM r WHERE classificacao = 'Novo'
  GROUP BY 1,2,3,4,5,6
),
m_pp_novos_qtd AS (
  SELECT CAST(canal AS STRING) AS c, pp_eq AS e, pp_reg AS rg,
         CAST(competencia AS DATE) AS mes_ref, pp_tam AS t,
         COUNT(*) AS val
  FROM pp WHERE status_recorrente = 'Novo'
  GROUP BY 1,2,3,4,5
),

-- I: # Churn
m_churn_qtd AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         dt_cancelado AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS val
  FROM r WHERE classificacao_churn = 'CHURN' AND dt_cancelado IS NOT NULL
  GROUP BY 1,2,3,4,5,6
),
m_pp_churn_qtd AS (
  SELECT CAST(canal AS STRING) AS c, pp_eq AS e, pp_reg AS rg,
         CAST(mes_churn AS DATE) AS mes_ref, pp_tam AS t,
         COUNT(*) AS val
  FROM pp WHERE status_recorrente = 'Churn' AND mes_churn IS NOT NULL
  GROUP BY 1,2,3,4,5
),

-- K: $ Base Inicial
m_base_ini_val AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         DATE_ADD(mes_base, INTERVAL 1 MONTH) AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(coalesce(faturado_mes,0)) AS val
  FROM r WHERE (dt_cancelado IS NULL OR dt_cancelado <> mes_base) and coalesce(faturado_mes,0) > 0
  GROUP BY 1,2,3,4,5,6
),
m_pp_base_ini_val AS (
  SELECT CAST(canal AS STRING) AS c, pp_eq AS e, pp_reg AS rg,
         DATE_ADD(CAST(competencia AS DATE), INTERVAL 1 MONTH) AS mes_ref, pp_tam AS t,
         SUM(CAST(valor_mensal AS FLOAT64)) AS val
  FROM pp WHERE (mes_churn IS NULL OR CAST(mes_churn AS DATE) <> CAST(competencia AS DATE) 
  AND CAST(valor_mensal AS FLOAT64) > 0)
  GROUP BY 1,2,3,4,5
),

-- L: $ Novos
m_novos_val AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(faturado_mes) AS val
  FROM r WHERE classificacao = 'Novo'
  GROUP BY 1,2,3,4,5,6
),
m_pp_novos_val AS (
  SELECT CAST(canal AS STRING) AS c, pp_eq AS e, pp_reg AS rg,
         CAST(competencia AS DATE) AS mes_ref, pp_tam AS t,
         SUM(CAST(valor_mensal AS FLOAT64)) AS val
  FROM pp WHERE status_recorrente = 'Novo'
  GROUP BY 1,2,3,4,5
),

-- M: $ Up
m_up_val AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(delta) AS val
  FROM r WHERE classificacao = 'Upgrade'
  GROUP BY 1,2,3,4,5,6
),

-- N: $ Down
m_down_val AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(delta) AS val
  FROM r WHERE classificacao = 'Downgrade'
  GROUP BY 1,2,3,4,5,6
),

-- O: $ Churn
m_churn_val AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         dt_cancelado AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(faturado_mes) AS val
  FROM r WHERE classificacao_churn = 'CHURN' AND dt_cancelado IS NOT NULL
  GROUP BY 1,2,3,4,5,6
),
m_pp_churn_val AS (
  SELECT CAST(canal AS STRING) AS c, pp_eq AS e, pp_reg AS rg,
         CAST(mes_churn AS DATE) AS mes_ref, pp_tam AS t,
         SUM(CAST(valor_mensal AS FLOAT64)) AS val
  FROM pp WHERE status_recorrente = 'Churn' AND mes_churn IS NOT NULL
  GROUP BY 1,2,3,4,5
),

-- Q: $ Recuperados
m_recup_val AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(faturado_mes) AS val
  FROM r WHERE classificacao_churn = 'CHURN - Recuperado'
  GROUP BY 1,2,3,4,5,6
),

-- R: $ Recuperados (novos)
m_recup_novos_val AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(faturado_mes) AS val
  FROM r WHERE classificacao_churn = 'CHURN - Recuperado' AND classificacao = 'Novo'
  GROUP BY 1,2,3,4,5,6
),

-- T/U: Campanha qtd/val
m_camp_qtd AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS val
  FROM r WHERE faturado_mes_campanha IS NOT NULL AND faturado_mes_campanha <> 0
  GROUP BY 1,2,3,4,5,6
),
m_camp_val AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(faturado_mes_campanha) AS val
  FROM r GROUP BY 1,2,3,4,5,6
),

-- V/W: SVA qtd/val
m_sva_qtd AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS val
  FROM r WHERE (faturado_mes_bairro_vip IS NOT NULL AND faturado_mes_bairro_vip <> 0)
            OR (faturado_mes_topo_fixo IS NOT NULL AND faturado_mes_topo_fixo <> 0)
  GROUP BY 1,2,3,4,5,6
),
m_sva_val AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(COALESCE(faturado_mes_bairro_vip,0) + COALESCE(faturado_mes_topo_fixo,0)) AS val
  FROM r GROUP BY 1,2,3,4,5,6
),

-- AH/AI: Up/Down qtd
m_up_qtd AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS val
  FROM r WHERE classificacao = 'Upgrade'
  GROUP BY 1,2,3,4,5,6
),
m_down_qtd AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS val
  FROM r WHERE classificacao = 'Downgrade'
  GROUP BY 1,2,3,4,5,6
),

-- Pagamentos CB (X/Y/Z agrupados)
/*m_cb_pagamentos AS (
  SELECT canal AS c, coordenador_ajustado AS e, regionalizacao AS rg,
         SAFE.PARSE_DATE('%d/%m/%Y', mes_pago) AS mes_ref, tamanho AS t,
         COALESCE(id_migracao_pro_field, 'Não') as tr,
         SUM(SAFE_CAST(antecipado AS FLOAT64)) AS adiantado_val,
         SUM(SAFE_CAST(no_mes AS FLOAT64)) AS no_mes_val,
         SUM(SAFE_CAST(transcorrido AS FLOAT64)) AS transcorrido_val,
         COUNTIF(SAFE_CAST(antecipado AS FLOAT64) <> 0) AS adiantado_qtd,
         COUNTIF(SAFE_CAST(no_mes AS FLOAT64) <> 0) AS no_mes_qtd,
         COUNTIF(SAFE_CAST(transcorrido AS FLOAT64) <> 0) AS transcorrido_qtd
  FROM cb
  GROUP BY 1,2,3,4,5,6
),*/

m_cb_pagamentos AS (
  SELECT 
    COALESCE(TRIM(canal), '') AS c, 
    COALESCE(TRIM(coordenador_ajustado), '') AS e, 
    CASE 
    WHEN regionalizacao = 'RJ+MG+ES' THEN 'RJ'
    WHEN regionalizacao = 'N+NE+CO' THEN 'NE'
    ELSE TRIM(regionalizacao)
    END AS rg,
    SAFE.PARSE_DATE('%d/%m/%Y', mes_pago) AS mes_ref, 
    COALESCE(TRIM(tamanho), '') AS t,
    COALESCE(TRIM(id_migracao_pro_field), 'Não') as tr,
    SUM(SAFE_CAST(antecipado AS FLOAT64)) AS adiantado_val,
    SUM(SAFE_CAST(no_mes AS FLOAT64)) AS no_mes_val,
    SUM(SAFE_CAST(transcorrido AS FLOAT64)) AS transcorrido_val,
    COUNTIF(SAFE_CAST(antecipado AS FLOAT64) <> 0) AS adiantado_qtd,
    COUNTIF(SAFE_CAST(no_mes AS FLOAT64) <> 0) AS no_mes_qtd,
    COUNTIF(SAFE_CAST(transcorrido AS FLOAT64) <> 0) AS transcorrido_qtd
  FROM cb
  GROUP BY 1,2,3,4,5,6
),

-- AA/AB: Pagamento Campanha/SVA (receita)
m_pago_camp_val AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(pago_mes_campanha) AS val
  FROM r GROUP BY 1,2,3,4,5,6
),
m_pago_sva_val AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(COALESCE(pago_mes_bairro,0) + COALESCE(pago_mes_topo,0)) AS val
  FROM r GROUP BY 1,2,3,4,5,6
),

-- AF/AG: # Pagamento Campanha/SVA (usa cordenador, não coordenador_ajustado)
m_pago_camp_qtd AS (
  SELECT canal_conta AS c, cordenador AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(apoio_qtd_campanha) AS val
  FROM r GROUP BY 1,2,3,4,5,6
),
m_pago_sva_qtd AS (
  SELECT canal_conta AS c, cordenador AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(apoio_qtd_sva) AS val
  FROM r GROUP BY 1,2,3,4,5,6
),

-- Pago (AJ-AN): Base Ini / Novos / Up / Down / Churn com status_ts = '1-Paid'
m_base_ini_pago AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         DATE_ADD(mes_base, INTERVAL 1 MONTH) AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(faturado_mes) AS val
  FROM r WHERE status_ts = '1-Paid' AND (dt_cancelado IS NULL OR dt_cancelado <> mes_base)
  GROUP BY 1,2,3,4,5,6
),
m_novos_pago AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(faturado_mes) AS val
  FROM r WHERE classificacao = 'Novo' AND status_ts = '1-Paid'
  GROUP BY 1,2,3,4,5,6
),
m_up_pago AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(delta) AS val
  FROM r WHERE classificacao = 'Upgrade' AND status_ts = '1-Paid'
  GROUP BY 1,2,3,4,5,6
),
m_down_pago AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(delta) AS val
  FROM r WHERE classificacao = 'Downgrade' AND status_ts = '1-Paid'
  GROUP BY 1,2,3,4,5,6
),
m_churn_pago AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         dt_cancelado AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(faturado_mes) AS val
  FROM r WHERE classificacao_churn = 'CHURN' AND status_ts = '1-Paid' AND dt_cancelado IS NOT NULL
  GROUP BY 1,2,3,4,5,6
),
m_base_fin_pago AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(CASE WHEN status_ts = '1-Paid' THEN faturado_mes ELSE 0 END) AS val
  FROM r
  GROUP BY 1,2,3,4,5,6
),
m_recup_pago AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(faturado_mes) AS val
  FROM r WHERE classificacao_churn = 'CHURN - Recuperado' AND status_ts = '1-Paid'
  GROUP BY 1,2,3,4,5,6
),
m_recup_novos_pago AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(faturado_mes) AS val
  FROM r WHERE classificacao_churn = 'CHURN - Recuperado' AND classificacao = 'Novo' AND status_ts = '1-Paid'
  GROUP BY 1,2,3,4,5,6
),

-- Migração IN (AS-AZ): churn/up/down/base com status_migrado = 'Migrado'
m_churn_mig_in_qtd AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         dt_cancelado AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS val
  FROM r WHERE classificacao_churn = 'CHURN' AND status_migrado = 'Migrado' AND dt_cancelado IS NOT NULL
  GROUP BY 1,2,3,4,5,6
),
m_churn_mig_in_val AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         dt_cancelado AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(faturado_mes) AS val
  FROM r WHERE classificacao_churn = 'CHURN' AND status_migrado = 'Migrado' AND dt_cancelado IS NOT NULL
  GROUP BY 1,2,3,4,5,6
),
m_up_mig_in AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS qtd, SUM(delta) AS val
  FROM r WHERE classificacao = 'Upgrade' AND status_migrado = 'Migrado'
  GROUP BY 1,2,3,4,5,6
),
m_down_mig_in AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS qtd, SUM(delta) AS val
  FROM r WHERE classificacao = 'Downgrade' AND status_migrado = 'Migrado'
  GROUP BY 1,2,3,4,5,6
),
m_base_mig_in AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS qtd, SUM(faturado_mes) AS val
  FROM r WHERE status_migrado = 'Migrado'
  GROUP BY 1,2,3,4,5,6
),

-- Migração OUT (BA-BH): usa coordenador_ajustado_out e aux_canal_out
m_churn_mig_out_qtd AS (
  SELECT aux_canal_out AS c, coordenador_ajustado_out AS e, reg AS rg,
         dt_cancelado AS mes_ref, COALESCE(tam,'') AS t,
         COUNT(*) AS val
  FROM r WHERE classificacao_churn = 'CHURN' AND status_migrado = 'Migrado' AND dt_cancelado IS NOT NULL
  GROUP BY 1,2,3,4,5
),
m_churn_mig_out_val AS (
  SELECT aux_canal_out AS c, coordenador_ajustado_out AS e, reg AS rg,
         dt_cancelado AS mes_ref, COALESCE(tam,'') AS t,
         SUM(faturado_mes) AS val
  FROM r WHERE classificacao_churn = 'CHURN' AND status_migrado = 'Migrado' AND dt_cancelado IS NOT NULL
  GROUP BY 1,2,3,4,5
),
m_up_mig_out AS (
  SELECT aux_canal_out AS c, coordenador_ajustado_out AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t,
         COUNT(*) AS qtd, SUM(delta) AS val
  FROM r WHERE classificacao = 'Upgrade' AND status_migrado = 'Migrado'
  GROUP BY 1,2,3,4,5
),
m_down_mig_out AS (
  SELECT aux_canal_out AS c, coordenador_ajustado_out AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t,
         COUNT(*) AS qtd, SUM(delta) AS val
  FROM r WHERE classificacao = 'Downgrade' AND status_migrado = 'Migrado'
  GROUP BY 1,2,3,4,5
),
m_base_mig_out AS (
  SELECT aux_canal_out AS c, coordenador_ajustado_out AS e, reg AS rg,
         mes_base AS mes_ref, COALESCE(tam,'') AS t,
         COUNT(*) AS qtd, SUM(faturado_mes) AS val
  FROM r WHERE status_migrado = 'Migrado'
  GROUP BY 1,2,3,4,5
),

-- BI/BJ/BK/BL: CHURN IN/OUT BI (filtro adicional mes_base = dt_cancelado)
m_churn_bi_in AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         dt_cancelado AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         COUNT(*) AS qtd, SUM(faturado_mes) AS val
  FROM r WHERE classificacao_churn = 'CHURN' AND status_migrado = 'Migrado'
    AND dt_cancelado IS NOT NULL AND mes_base = dt_cancelado
  GROUP BY 1,2,3,4,5,6
),
m_churn_bi_out AS (
  SELECT aux_canal_out AS c, coordenador_ajustado_out AS e, reg AS rg,
         dt_cancelado AS mes_ref, COALESCE(tam,'') AS t,
         COUNT(*) AS qtd, SUM(faturado_mes) AS val
  FROM r WHERE classificacao_churn = 'CHURN' AND status_migrado = 'Migrado'
    AND dt_cancelado IS NOT NULL AND mes_base = dt_cancelado
  GROUP BY 1,2,3,4,5
),

-- BN/BO: Volume transcorrido (mês anterior)
/*m_vol_transcorrido AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         DATE_ADD(mes_base, INTERVAL 1 MONTH) AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(CASE
           WHEN day_base >= DATE_SUB(DATE_ADD(LAST_DAY(mes_base), INTERVAL 1 DAY), INTERVAL 6 DAY)
             AND day_base <= LAST_DAY(mes_base)
             AND (dt_cancelado IS NULL OR EXTRACT(MONTH FROM dt_cancelado) <> EXTRACT(MONTH FROM mes_base)
                  OR EXTRACT(YEAR FROM dt_cancelado) <> EXTRACT(YEAR FROM mes_base))
           THEN faturado_mes ELSE 0 END) AS val,
         COUNTIF(
           day_base >= DATE_SUB(DATE_ADD(LAST_DAY(mes_base), INTERVAL 1 DAY), INTERVAL 6 DAY)
           AND day_base <= LAST_DAY(mes_base)
           AND (dt_cancelado IS NULL OR EXTRACT(MONTH FROM dt_cancelado) <> EXTRACT(MONTH FROM mes_base)
                OR EXTRACT(YEAR FROM dt_cancelado) <> EXTRACT(YEAR FROM mes_base))
         ) AS qtd
  FROM r
  GROUP BY 1,2,3,4,5,6
),*/
-- BN/BO: Volume transcorrido (mês anterior)
/*m_vol_transcorrido AS (
  SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         DATE_ADD(mes_base, INTERVAL 1 MONTH) AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
         SUM(CASE
           WHEN day_base >= DATE_SUB(DATE_ADD(LAST_DAY(mes_base), INTERVAL 1 DAY), INTERVAL 6 DAY)
             AND day_base <= LAST_DAY(mes_base)
             AND (dt_cancelado IS NULL OR EXTRACT(MONTH FROM dt_cancelado) <> EXTRACT(MONTH FROM mes_base)
                  OR EXTRACT(YEAR FROM dt_cancelado) <> EXTRACT(YEAR FROM mes_base))
           THEN volume_transcorrido ELSE 0 END) AS val, 
         COUNTIF(
           day_base >= DATE_SUB(DATE_ADD(LAST_DAY(mes_base), INTERVAL 1 DAY), INTERVAL 6 DAY)
           AND day_base <= LAST_DAY(mes_base)
           AND (dt_cancelado IS NULL OR EXTRACT(MONTH FROM dt_cancelado) <> EXTRACT(MONTH FROM mes_base)
                OR EXTRACT(YEAR FROM dt_cancelado) <> EXTRACT(YEAR FROM mes_base))
           AND volume_transcorrido <> 0
         ) AS qtd
  FROM r
  GROUP BY 1,2,3,4,5,6
),*/
m_vol_transcorrido AS (SELECT canal_conta AS c, coordenador_ajustado AS e, reg AS rg,
         DATE_ADD(mes_base, INTERVAL 1 MONTH) AS mes_ref, COALESCE(tam,'') AS t, transf AS tr,
          sum(volume_transcorrido) as val,
          countif(volume_transcorrido > 0) as qtd
          FROM r
        GROUP BY 1,2,3,4,5,6),
        
-- PP: pagamentos no mês (PAID)
m_pp_paid AS (
  SELECT CAST(canal AS STRING) AS c, pp_eq AS e, pp_reg AS rg,
         CAST(competencia AS DATE) AS mes_ref, pp_tam AS t,
         COUNT(*) AS qtd, SUM(CAST(valor_mensal AS FLOAT64)) AS val
  FROM pp WHERE CAST(status AS STRING) = 'PAID'
  GROUP BY 1,2,3,4,5
)


-- ===== SELECT FINAL: JOINs =====
SELECT
  d.Canal, d.Equipe, d.Regiao_Macro, d.Mes_Base, d.Tamanho,

  -- G: # Base Inicial
  COALESCE(bi.val,0) + COALESCE(mi.val,0) - COALESCE(mo.val,0)
    + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppbi.val,0) END AS base_inicial_qtd,
  -- H: # Novos
  COALESCE(nq.val,0) + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppnq.val,0) END AS novos_qtd,
  -- I: # Churn
  COALESCE(cq.val,0) * -1 + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppcq.val,0) * -1 END AS churn_qtd,
  /*-- J: # Base Final (G+H+I + migIN - migOUT)
  (COALESCE(bi.val,0) + COALESCE(mi.val,0) - COALESCE(mo.val,0)
  + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppbi.val,0) END)
  + (COALESCE(nq.val,0) + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppnq.val,0) END)
  + (COALESCE(cq.val,0) * -1 + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppcq.val,0) * -1 END)
  + COALESCE(bmi.qtd,0) - COALESCE(bmo.qtd,0) AS base_final_qtd,*/

  -- K: $ Base Inicial
  COALESCE(biv.val,0) + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppbiv.val,0) END AS base_inicial_valor,
  -- L: $ Novos
  COALESCE(nv.val,0) + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppnv.val,0) END AS novos_valor,
  -- M: $ Up
  COALESCE(uv.val,0) AS up_valor,
  -- N: $ Down
  COALESCE(dv.val,0) AS down_valor,
  -- O: $ Churn
  COALESCE(cv.val,0) * -1 + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppcv.val,0) * -1 END AS churn_valor,
  -- P: $ Cancelamento total (= Q + O)
  /*(COALESCE(cv.val,0) * -1 + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppcv.val,0) * -1 END)
  + COALESCE(rv.val,0) AS cancelamento_total_valor,*/
  -- Q: $ Recuperados
  COALESCE(rv.val,0) AS recuperados_valor,
  -- R: $ Recuperados (novos)
  COALESCE(rnv.val,0) AS recuperados_novos_valor,
  -- S: $ Base Final (K+L+M+N+O + AY - BG)
  (COALESCE(biv.val,0) + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppbiv.val,0) END)
  + (COALESCE(nv.val,0) + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppnv.val,0) END)
  + COALESCE(uv.val,0) + COALESCE(dv.val,0)
  + (COALESCE(cv.val,0) * -1 + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppcv.val,0) * -1 END)
  + COALESCE(bmi.val,0) - COALESCE(bmo.val,0) AS base_final_valor,

  -- T: # Campanha
  COALESCE(cmpq.val,0) AS campanha_qtd,
  -- U: $ Campanha
  COALESCE(cmpv.val,0) AS campanha_valor,
  -- V: # SVA
  COALESCE(svaq.val,0) AS sva_qtd,
  -- W: $ SVA
  COALESCE(svav.val,0) AS sva_valor,

  -- X: $ Pagamentos Adiantados
  COALESCE(cbp.adiantado_val,0) AS pagamentos_adiantados_valor,
  -- Y: $ Pagamentos no mês + PP PAID
  COALESCE(cbp.no_mes_val,0) + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppp.val,0) END AS pagamentos_no_mes_valor,
  -- Z: $ Pagamentos Transcorridos
  COALESCE(cbp.transcorrido_val,0) AS pagamentos_transcorridos_valor,
  -- AA: $ Pagamento Campanha
  COALESCE(pcv.val,0) AS pagamento_campanha_valor,
  -- AB: $ Pagamento SVA
  COALESCE(psv.val,0) AS pagamento_sva_valor,

  -- AC: # Pagamentos Adiantados
  COALESCE(cbp.adiantado_qtd,0) AS pagamentos_adiantados_qtd,
  -- AD: # Pagamentos no mês + PP PAID qtd
  COALESCE(cbp.no_mes_qtd,0) + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppp.qtd,0) END AS pagamentos_no_mes_qtd,
  -- AE: # Pagamentos Transcorridos
  COALESCE(cbp.transcorrido_qtd,0) AS pagamentos_transcorridos_qtd,
  -- AF: # Pagamento Campanha
  COALESCE(pcq.val,0) AS pagamento_campanha_qtd,
  -- AG: # Pagamento SVA
  COALESCE(psq.val,0) AS pagamento_sva_qtd,

  -- AH: # Up
  COALESCE(uq.val,0) AS up_qtd,
  -- AI: # Down
  COALESCE(dq.val,0) AS down_qtd,

  -- AJ: $ Base Inicial Pago
  COALESCE(bip.val,0) + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppbiv.val,0) END AS base_inicial_pago_valor,
  -- AK: $ Novos Pago
  COALESCE(np.val,0) + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppnv.val,0) END AS novos_pago_valor,
  -- AL: $ Up Pago
  COALESCE(upg.val,0) AS up_pago_valor,
  -- AM: $ Down Pago
  COALESCE(dpg.val,0) AS down_pago_valor,
  -- AN: $ Churn Pago
  COALESCE(cpg.val,0) * -1 + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppcv.val,0) * -1 END AS churn_pago_valor,
  -- AO: $ Cancelamento total Pago
  /*(COALESCE(cpg.val,0) + CASE WHEN d.Transferencias = 'Sim' THEN 0 ELSE COALESCE(ppcv.val,0) END)
  + COALESCE(rp.val,0) AS cancelamento_total_pago_valor,*/
  -- AP: $ Recuperados Pago
  COALESCE(rp.val,0) AS recuperados_pago_valor,
  -- AQ: $ Recuperados (novos) Pago
  COALESCE(rnp.val,0) AS recuperados_novos_pago_valor,
  -- AR: $ Base Final Pago
  /*COALESCE(bip.val,0) + COALESCE(np.val,0) + COALESCE(upg.val,0) + (abs(COALESCE(dpg.val,0))
  + abs(COALESCE(cpg.val,0)))*-1 AS base_final_pago_valor,*/

  -- AS: # Churn Migração IN
  COALESCE(cmiq.val,0) * -1 AS churn_migracao_in_qtd,
  -- AT: # Up Migração IN
  COALESCE(umi.qtd,0) AS up_migracao_in_qtd,
  -- AU: # Down Migração IN
  COALESCE(dmi.qtd,0) AS down_migracao_in_qtd,
  -- AV: $ Churn Migração IN
  COALESCE(cmiv.val,0) * -1 AS churn_migracao_in_valor,
  -- AW: $ Up Migração IN
  COALESCE(umi.val,0) AS up_migracao_in_valor,
  -- AX: $ Down Migração IN
  COALESCE(dmi.val,0) AS down_migracao_in_valor,
  -- AY: $ Base Migração IN
  COALESCE(bmi.val,0) AS base_migracao_in_valor,
  -- AZ: # Base Migração IN
  COALESCE(bmi.qtd,0) AS base_migracao_in_qtd,
  -- BA: # Churn Migração OUT
  COALESCE(cmoq.val,0) * -1 AS churn_migracao_out_qtd,
  -- BB: # Up Migração OUT
  COALESCE(umo.qtd,0) AS up_migracao_out_qtd,
  -- BC: # Down Migração OUT
  COALESCE(dmo.qtd,0) AS down_migracao_out_qtd,
  -- BD: $ Churn Migração OUT
  COALESCE(cmov.val,0) * -1 AS churn_migracao_out_valor,
  -- BE: $ Up Migração OUT
  COALESCE(umo.val,0) AS up_migracao_out_valor,
  -- BF: $ Down Migração OUT
  COALESCE(dmo.val,0) AS down_migracao_out_valor,
  -- BG: $ Base Migração OUT
  COALESCE(bmo.val,0) AS base_migracao_out_valor,
  -- BH: # Base Migração OUT
  COALESCE(bmo.qtd,0) AS base_migracao_out_qtd,

  -- BI: CHURN IN # (BI)
  COALESCE(cbin.qtd,0) * -1 AS churn_in_bi_qtd,
  -- BJ: CHURN IN $ (BI)
  COALESCE(cbin.val,0) * -1 AS churn_in_bi_valor,
  -- BK: CHURN OUT # (BI)
  COALESCE(cbout.qtd,0) * -1 AS churn_out_bi_qtd,
  -- BL: CHURN OUT $ (BI)
  COALESCE(cbout.val,0) * -1 AS churn_out_bi_valor,

  -- BN: $ Volume transcorrido
  COALESCE(vt.val,0) AS volume_transcorrido_valor,
  -- BO: # Volume transcorrido
  COALESCE(vt.qtd,0) AS volume_transcorrido_qtd,

  -- BM: Transferências
  d.Transferencias,
  -- BP: Chave
  CONCAT(d.Canal, d.Equipe) AS chave_equipe_coordenador

FROM dimensoes d
/*LEFT JOIN m_base_fin_pago bfpg ON bfpg.c=d.Canal and bfpg.e=d.Equipe AND bfpg.rg=d.Regiao_Macro AND bfpg.mes_ref=d.Mes_Base AND bfpg.t=d.Tamanho AND bfpg.tr=d.Transferencias*/
LEFT JOIN m_base_ini_qtd bi ON bi.c=d.Canal AND bi.e=d.Equipe AND bi.rg=d.Regiao_Macro AND bi.mes_ref=d.Mes_Base AND bi.t=d.Tamanho AND bi.tr=d.Transferencias
LEFT JOIN m_mig_in_qtd mi ON mi.c=d.Canal AND mi.e=d.Equipe AND mi.rg=d.Regiao_Macro AND mi.mes_ref=d.Mes_Base AND mi.t=d.Tamanho AND mi.tr=d.Transferencias
LEFT JOIN m_mig_out_qtd mo ON mo.c=d.Canal AND mo.e=d.Equipe AND mo.rg=d.Regiao_Macro AND mo.mes_ref=d.Mes_Base AND mo.t=d.Tamanho --AND mo.tr=d.Transferencias
LEFT JOIN m_pp_base_ini ppbi ON ppbi.c=d.Canal AND ppbi.e=d.Equipe AND ppbi.rg=d.Regiao_Macro AND ppbi.mes_ref=d.Mes_Base AND ppbi.t=d.Tamanho
LEFT JOIN m_novos_qtd nq ON nq.c=d.Canal AND nq.e=d.Equipe AND nq.rg=d.Regiao_Macro AND nq.mes_ref=d.Mes_Base AND nq.t=d.Tamanho AND nq.tr=d.Transferencias
LEFT JOIN m_pp_novos_qtd ppnq ON ppnq.c=d.Canal AND ppnq.e=d.Equipe AND ppnq.rg=d.Regiao_Macro AND ppnq.mes_ref=d.Mes_Base AND ppnq.t=d.Tamanho
LEFT JOIN m_churn_qtd cq ON cq.c=d.Canal AND cq.e=d.Equipe AND cq.rg=d.Regiao_Macro AND cq.mes_ref=d.Mes_Base AND cq.t=d.Tamanho AND cq.tr=d.Transferencias
LEFT JOIN m_pp_churn_qtd ppcq ON ppcq.c=d.Canal AND ppcq.e=d.Equipe AND ppcq.rg=d.Regiao_Macro AND ppcq.mes_ref=d.Mes_Base AND ppcq.t=d.Tamanho
LEFT JOIN m_base_ini_val biv ON biv.c=d.Canal AND biv.e=d.Equipe AND biv.rg=d.Regiao_Macro AND biv.mes_ref=d.Mes_Base AND biv.t=d.Tamanho AND biv.tr=d.Transferencias
LEFT JOIN m_pp_base_ini_val ppbiv ON ppbiv.c=d.Canal AND ppbiv.e=d.Equipe AND ppbiv.rg=d.Regiao_Macro AND ppbiv.mes_ref=d.Mes_Base AND ppbiv.t=d.Tamanho
LEFT JOIN m_novos_val nv ON nv.c=d.Canal AND nv.e=d.Equipe AND nv.rg=d.Regiao_Macro AND nv.mes_ref=d.Mes_Base AND nv.t=d.Tamanho AND nv.tr=d.Transferencias
LEFT JOIN m_pp_novos_val ppnv ON ppnv.c=d.Canal AND ppnv.e=d.Equipe AND ppnv.rg=d.Regiao_Macro AND ppnv.mes_ref=d.Mes_Base AND ppnv.t=d.Tamanho
LEFT JOIN m_up_val uv ON uv.c=d.Canal AND uv.e=d.Equipe AND uv.rg=d.Regiao_Macro AND uv.mes_ref=d.Mes_Base AND uv.t=d.Tamanho AND uv.tr=d.Transferencias
LEFT JOIN m_down_val dv ON dv.c=d.Canal AND dv.e=d.Equipe AND dv.rg=d.Regiao_Macro AND dv.mes_ref=d.Mes_Base AND dv.t=d.Tamanho AND dv.tr=d.Transferencias
LEFT JOIN m_churn_val cv ON cv.c=d.Canal AND cv.e=d.Equipe AND cv.rg=d.Regiao_Macro AND cv.mes_ref=d.Mes_Base AND cv.t=d.Tamanho AND cv.tr=d.Transferencias
LEFT JOIN m_pp_churn_val ppcv ON ppcv.c=d.Canal AND ppcv.e=d.Equipe AND ppcv.rg=d.Regiao_Macro AND ppcv.mes_ref=d.Mes_Base AND ppcv.t=d.Tamanho
LEFT JOIN m_recup_val rv ON rv.c=d.Canal AND rv.e=d.Equipe AND rv.rg=d.Regiao_Macro AND rv.mes_ref=d.Mes_Base AND rv.t=d.Tamanho AND rv.tr=d.Transferencias
LEFT JOIN m_recup_novos_val rnv ON rnv.c=d.Canal AND rnv.e=d.Equipe AND rnv.rg=d.Regiao_Macro AND rnv.mes_ref=d.Mes_Base AND rnv.t=d.Tamanho AND rnv.tr=d.Transferencias
LEFT JOIN m_camp_qtd cmpq ON cmpq.c=d.Canal AND cmpq.e=d.Equipe AND cmpq.rg=d.Regiao_Macro AND cmpq.mes_ref=d.Mes_Base AND cmpq.t=d.Tamanho AND cmpq.tr=d.Transferencias
LEFT JOIN m_camp_val cmpv ON cmpv.c=d.Canal AND cmpv.e=d.Equipe AND cmpv.rg=d.Regiao_Macro AND cmpv.mes_ref=d.Mes_Base AND cmpv.t=d.Tamanho AND cmpv.tr=d.Transferencias
LEFT JOIN m_sva_qtd svaq ON svaq.c=d.Canal AND svaq.e=d.Equipe AND svaq.rg=d.Regiao_Macro AND svaq.mes_ref=d.Mes_Base AND svaq.t=d.Tamanho AND svaq.tr=d.Transferencias
LEFT JOIN m_sva_val svav ON svav.c=d.Canal AND svav.e=d.Equipe AND svav.rg=d.Regiao_Macro AND svav.mes_ref=d.Mes_Base AND svav.t=d.Tamanho AND svav.tr=d.Transferencias
LEFT JOIN m_cb_pagamentos cbp ON cbp.c=d.Canal AND cbp.e=d.Equipe AND cbp.rg=d.Regiao_Macro AND cbp.mes_ref=d.Mes_Base AND cbp.t=d.Tamanho AND cbp.tr=d.Transferencias
LEFT JOIN m_pago_camp_val pcv ON pcv.c=d.Canal AND pcv.e=d.Equipe AND pcv.rg=d.Regiao_Macro AND pcv.mes_ref=d.Mes_Base AND pcv.t=d.Tamanho AND pcv.tr=d.Transferencias
LEFT JOIN m_pago_sva_val psv ON psv.c=d.Canal AND psv.e=d.Equipe AND psv.rg=d.Regiao_Macro AND psv.mes_ref=d.Mes_Base AND psv.t=d.Tamanho AND psv.tr=d.Transferencias
LEFT JOIN m_pago_camp_qtd pcq ON pcq.c=d.Canal AND pcq.e=d.Equipe AND pcq.rg=d.Regiao_Macro AND pcq.mes_ref=d.Mes_Base AND pcq.t=d.Tamanho AND pcq.tr=d.Transferencias
LEFT JOIN m_pago_sva_qtd psq ON psq.c=d.Canal AND psq.e=d.Equipe AND psq.rg=d.Regiao_Macro AND psq.mes_ref=d.Mes_Base AND psq.t=d.Tamanho AND psq.tr=d.Transferencias
LEFT JOIN m_up_qtd uq ON uq.c=d.Canal AND uq.e=d.Equipe AND uq.rg=d.Regiao_Macro AND uq.mes_ref=d.Mes_Base AND uq.t=d.Tamanho AND uq.tr=d.Transferencias
LEFT JOIN m_down_qtd dq ON dq.c=d.Canal AND dq.e=d.Equipe AND dq.rg=d.Regiao_Macro AND dq.mes_ref=d.Mes_Base AND dq.t=d.Tamanho AND dq.tr=d.Transferencias
LEFT JOIN m_base_ini_pago bip ON bip.c=d.Canal AND bip.e=d.Equipe AND bip.rg=d.Regiao_Macro AND bip.mes_ref=d.Mes_Base AND bip.t=d.Tamanho AND bip.tr=d.Transferencias
LEFT JOIN m_novos_pago np ON np.c=d.Canal AND np.e=d.Equipe AND np.rg=d.Regiao_Macro AND np.mes_ref=d.Mes_Base AND np.t=d.Tamanho AND np.tr=d.Transferencias
LEFT JOIN m_up_pago upg ON upg.c=d.Canal AND upg.e=d.Equipe AND upg.rg=d.Regiao_Macro AND upg.mes_ref=d.Mes_Base AND upg.t=d.Tamanho AND upg.tr=d.Transferencias
LEFT JOIN m_down_pago dpg ON dpg.c=d.Canal AND dpg.e=d.Equipe AND dpg.rg=d.Regiao_Macro AND dpg.mes_ref=d.Mes_Base AND dpg.t=d.Tamanho AND dpg.tr=d.Transferencias
LEFT JOIN m_churn_pago cpg ON cpg.c=d.Canal AND cpg.e=d.Equipe AND cpg.rg=d.Regiao_Macro AND cpg.mes_ref=d.Mes_Base AND cpg.t=d.Tamanho AND cpg.tr=d.Transferencias
LEFT JOIN m_recup_pago rp ON rp.c=d.Canal AND rp.e=d.Equipe AND rp.rg=d.Regiao_Macro AND rp.mes_ref=d.Mes_Base AND rp.t=d.Tamanho AND rp.tr=d.Transferencias
LEFT JOIN m_recup_novos_pago rnp ON rnp.c=d.Canal AND rnp.e=d.Equipe AND rnp.rg=d.Regiao_Macro AND rnp.mes_ref=d.Mes_Base AND rnp.t=d.Tamanho AND rnp.tr=d.Transferencias
LEFT JOIN m_churn_mig_in_qtd cmiq ON cmiq.c=d.Canal AND cmiq.e=d.Equipe AND cmiq.rg=d.Regiao_Macro AND cmiq.mes_ref=d.Mes_Base AND cmiq.t=d.Tamanho AND cmiq.tr=d.Transferencias
LEFT JOIN m_churn_mig_in_val cmiv ON cmiv.c=d.Canal AND cmiv.e=d.Equipe AND cmiv.rg=d.Regiao_Macro AND cmiv.mes_ref=d.Mes_Base AND cmiv.t=d.Tamanho AND cmiv.tr=d.Transferencias
LEFT JOIN m_up_mig_in umi ON umi.c=d.Canal AND umi.e=d.Equipe AND umi.rg=d.Regiao_Macro AND umi.mes_ref=d.Mes_Base AND umi.t=d.Tamanho AND umi.tr=d.Transferencias
LEFT JOIN m_down_mig_in dmi ON dmi.c=d.Canal AND dmi.e=d.Equipe AND dmi.rg=d.Regiao_Macro AND dmi.mes_ref=d.Mes_Base AND dmi.t=d.Tamanho AND dmi.tr=d.Transferencias
LEFT JOIN m_base_mig_in bmi ON bmi.c=d.Canal AND bmi.e=d.Equipe AND bmi.rg=d.Regiao_Macro AND bmi.mes_ref=d.Mes_Base AND bmi.t=d.Tamanho AND bmi.tr=d.Transferencias
LEFT JOIN m_churn_mig_out_qtd cmoq ON cmoq.c=d.Canal AND cmoq.e=d.Equipe AND cmoq.rg=d.Regiao_Macro AND cmoq.mes_ref=d.Mes_Base AND cmoq.t=d.Tamanho --AND cmoq.tr=d.Transferencias
LEFT JOIN m_churn_mig_out_val cmov ON cmov.c=d.Canal AND cmov.e=d.Equipe AND cmov.rg=d.Regiao_Macro AND cmov.mes_ref=d.Mes_Base AND cmov.t=d.Tamanho --AND cmov.tr=d.Transferencias
LEFT JOIN m_up_mig_out umo ON umo.c=d.Canal AND umo.e=d.Equipe AND umo.rg=d.Regiao_Macro AND umo.mes_ref=d.Mes_Base AND umo.t=d.Tamanho --AND umo.tr=d.Transferencias
LEFT JOIN m_down_mig_out dmo ON dmo.c=d.Canal AND dmo.e=d.Equipe AND dmo.rg=d.Regiao_Macro AND dmo.mes_ref=d.Mes_Base AND dmo.t=d.Tamanho --AND dmo.tr=d.Transferencias
LEFT JOIN m_base_mig_out bmo ON bmo.c=d.Canal AND bmo.e=d.Equipe AND bmo.rg=d.Regiao_Macro AND bmo.mes_ref=d.Mes_Base AND bmo.t=d.Tamanho --AND bmo.tr=d.Transferencias
LEFT JOIN m_churn_bi_in cbin ON cbin.c=d.Canal AND cbin.e=d.Equipe AND cbin.rg=d.Regiao_Macro AND cbin.mes_ref=d.Mes_Base AND cbin.t=d.Tamanho AND cbin.tr=d.Transferencias
LEFT JOIN m_churn_bi_out cbout ON cbout.c=d.Canal AND cbout.e=d.Equipe AND cbout.rg=d.Regiao_Macro AND cbout.mes_ref=d.Mes_Base AND cbout.t=d.Tamanho --AND cbout.tr=d.Transferencias
LEFT JOIN m_vol_transcorrido vt ON vt.c=d.Canal AND vt.e=d.Equipe AND vt.rg=d.Regiao_Macro AND vt.mes_ref=d.Mes_Base AND vt.t=d.Tamanho AND vt.tr=d.Transferencias
LEFT JOIN m_pp_paid ppp ON ppp.c=d.Canal AND ppp.e=d.Equipe AND ppp.rg=d.Regiao_Macro AND ppp.mes_ref=d.Mes_Base AND ppp.t=d.Tamanho

--WHERE Mes_base = date_trunc(current_date(),month)
ORDER BY d.Mes_Base DESC, d.Canal, d.Equipe
)