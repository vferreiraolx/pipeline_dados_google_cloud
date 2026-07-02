-- =============================================================================
-- Tabela Derivada: receita_enriquecida
-- =============================================================================
-- Descrição: Replica a aba "Receita 4.0/SVA" do Sheets - adiciona colunas
--            calculadas à re_gold_receita_unificado_air: Estado Depara,
--            Tamanho ajustado, Coordenador ajustado, status_migrado,
--            aux_canal_out, coordenador_ajustado_out, flags auxiliares.
--
-- Esta tabela é a BASE que todas as abas BD consultam via SUMIFS/COUNTIFS.
--
-- Tabelas de origem:
--   - conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air
--
-- Modo de escrita: WRITE_TRUNCATE (substituição completa a cada execução)
-- =============================================================================

WITH base_com_lag AS (
  SELECT
    r.*,
    -- LAG para detectar migração (coluna AH do Sheets)
    LAG(canal_conta) OVER (PARTITION BY advertiser_id ORDER BY mes_base) AS canal_anterior,
    LAG(cordenador) OVER (PARTITION BY advertiser_id ORDER BY mes_base) AS coordenador_anterior
  FROM `conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air` r
),

-- Aba "Desconto faseado": advertiser_ids com desconto faseado no Salesforce
desconto_faseado AS (
  SELECT DISTINCT advertiser_id
  FROM `conect-python-g-sheets.planejamento_comercial.desconto_faseado`
  WHERE advertiser_id IS NOT NULL
),

-- Aba "Transferências": advertiser_ids que migraram para Field
-- Derivado da própria base: qualquer advertiser que já teve status_migrado
-- e agora está no canal Field
-- TODO: Quando tabela `transferencias` existir no BQ, substituir por SELECT DISTINCT advertiser_id FROM transferencias
transferencias AS (
  SELECT DISTINCT advertiser_id
  FROM `conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air`
  WHERE canal_conta = 'Field'
    AND classificacao <> 'Novo'
    AND advertiser_id IN (
      SELECT DISTINCT a.advertiser_id
      FROM `conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air` a
      WHERE a.canal_conta <> 'Field'
    )
)


SELECT
  b.advertiser_id,
  b.mes_base,
  b.tamanho,
  b.pacote,
  b.estado,
  b.municipio,
  b.ultimo_mes_pagamento,
  b.status_ts,
  b.faturado_mes,
  b.classificacao,
  b.classificacao_rec,
  b.classificacao_churn,
  b.vigencia_bt,
  b.dt_cancelado,
  b.delta,
  b.day_base,
  b.day_churn,
  b.faturado_mes_campanha,
  b.status_ts_campanha,
  b.pago_mes_campanha,
  b.faturado_mes_bairro_vip,
  b.status_ts_bairro_vip,
  b.pago_mes_bairro,
  b.faturado_mes_topo_fixo,
  b.status_ts_topo_fixo,
  b.pago_mes_topo,
  b.total_faturado_sva,
  b.total_pago_sva,
  b.canal_conta,
  b.dono_conta,
  b.dt,
  b.cordenador,
  b.advertiser_industry,

  -- Coluna AK: Estado Depara
  CASE
    WHEN b.estado IS NULL OR TRIM(CAST(b.estado AS STRING)) = '' THEN ''
    WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(b.estado AS STRING))), r'^(RS|SC|PR)$') THEN 'Sul'
    WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(b.estado AS STRING))), r'^(MG|ES)$') THEN 'MG/ES'
    WHEN UPPER(TRIM(CAST(b.estado AS STRING))) = 'RJ' THEN 'RJ'
    WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(b.estado AS STRING))), r'^(MS|MT|GO|DF|TO|PA|AP|RO|AC|AM)$') THEN 'NO/CO'
    WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(b.estado AS STRING))), r'^(BA|PI|MA|CE|RN|PB|PE|AL|SE)$') THEN 'NE'
    WHEN UPPER(TRIM(CAST(b.estado AS STRING))) = 'SP' AND UPPER(TRIM(CAST(b.municipio AS STRING))) = 'SÃO PAULO' THEN 'Sp Capital'
    WHEN UPPER(TRIM(CAST(b.estado AS STRING))) = 'SP' AND (b.municipio IS NULL OR UPPER(TRIM(CAST(b.municipio AS STRING))) <> 'SÃO PAULO') THEN 'SP Interior & Litoral'
    ELSE 'Outros'
  END AS regionalizacao,

  -- Coluna AL: Apoio Qtd Campanha (1 se tem pago_mes_campanha, senão vazio)
  CASE
    WHEN b.advertiser_id IS NOT NULL AND b.pago_mes_campanha IS NOT NULL AND b.pago_mes_campanha <> 0 THEN 1
    ELSE NULL
  END AS apoio_qtd_campanha,

  -- Coluna AM: Apoio Qtd SVA (1 se tem pago_mes_bairro ou pago_mes_topo)
  CASE
    WHEN b.advertiser_id IS NOT NULL
      AND ((b.pago_mes_topo IS NOT NULL AND b.pago_mes_topo <> 0) OR (b.pago_mes_bairro IS NOT NULL AND b.pago_mes_bairro <> 0))
    THEN 1
    ELSE NULL
  END AS apoio_qtd_sva,

  -- Coluna AN: ID & DATA (chave composta)
  CONCAT(CAST(b.advertiser_id AS STRING), CAST(b.mes_base AS STRING)) AS id_e_data,

  -- Coluna AO: ID ajustado
  CONCAT(CAST(b.advertiser_id AS STRING), CAST(b.ultimo_mes_pagamento AS STRING)) AS id_ajustado,

  -- Coluna AP: Tamanho Nr (extrai número do pacote)
  REGEXP_EXTRACT(b.pacote, r'\d+') AS tamanho_nr,

  -- Coluna AQ/AS: Tamanho ajustado
  -- Lógica Sheets: SE contém "Inser" → usa tamanho original; senão usa faixas numéricas
  -- TODO: Quando tabela tamanhos_ajustados existir no BQ, adicionar LEFT JOIN para casos "Inser"
  CASE
    WHEN b.pacote IS NOT NULL AND REGEXP_CONTAINS(b.pacote, r'(?i)Inser')
      THEN COALESCE(b.tamanho, b.pacote)
    WHEN SAFE_CAST(REGEXP_EXTRACT(b.pacote, r'\d+') AS INT64) <= 25 THEN 'PP'
    WHEN SAFE_CAST(REGEXP_EXTRACT(b.pacote, r'\d+') AS INT64) <= 80 THEN 'P'
    WHEN SAFE_CAST(REGEXP_EXTRACT(b.pacote, r'\d+') AS INT64) <= 600 THEN 'M'
    WHEN SAFE_CAST(REGEXP_EXTRACT(b.pacote, r'\d+') AS INT64) > 600 THEN 'G'
    ELSE COALESCE(b.tamanho, '')
  END AS tamanho_ajustado,

  -- Coluna AR: Coordenador ajustado
  CASE
    WHEN UPPER(TRIM(CAST(b.canal_conta AS STRING))) = 'ONLINE' THEN 'ONLINE'
    WHEN UPPER(TRIM(CAST(b.canal_conta AS STRING))) = 'ND' THEN 'ND'
    ELSE COALESCE(UPPER(TRIM(b.cordenador)),'')
  END AS coordenador_ajustado,

  -- Coluna AH: status_migrado
  CASE
    WHEN b.classificacao <> 'Novo'
      AND b.canal_anterior IS NOT NULL
      AND b.canal_anterior <> b.canal_conta
    THEN 'Migrado'
    ELSE NULL
  END AS status_migrado,

  -- Coluna AI: aux_canal_out (canal anterior - de onde saiu)
  b.canal_anterior AS aux_canal_out,

  -- Coluna AJ: aux_coord_out (coordenador anterior)
  b.coordenador_anterior AS aux_coord_out,

  -- Coluna AV: Coordenador ajustado OUT (coordenador ajustado do mês anterior, para migrados)
  CASE
    WHEN b.classificacao <> 'Novo'
      AND b.canal_anterior IS NOT NULL
      AND b.canal_anterior <> b.canal_conta
    THEN
      CASE
        WHEN b.canal_anterior = 'Online' THEN 'Online'
        WHEN b.canal_anterior = 'ND' THEN 'ND'
        ELSE b.coordenador_anterior
      END
    ELSE NULL
  END AS coordenador_ajustado_out,

  -- Coluna AT: Chave churn
  CONCAT(CAST(b.advertiser_id AS STRING), CAST(b.dt_cancelado AS STRING)) AS chave_churn,

  -- Coluna AU: ID Migração Pró Field?
  -- Lógica Sheets: SE canal = "Field" E advertiser_id existe na aba Transferências → "Sim"; senão "Não"
  CASE
    WHEN b.canal_conta = 'Field' AND t.advertiser_id IS NOT NULL THEN 'Sim'
    ELSE 'Não'
  END AS id_migracao_pro_field,

  -- Coluna AW: Desconto faseado
  -- Lógica Sheets: XLOOKUP no advertiser_id na aba 'Desconto faseado' → se encontra "Sim", senão "Não"
  CASE
    WHEN df.advertiser_id IS NOT NULL THEN 'Sim'
    ELSE 'Não'
  END AS desconto_faseado,

  -- Colunas AX/AY: Data_Vencimento_Cohort e Data_Pagamento_Cohort (da radar)
  rc.data_vencimento_cohort,
  rc.data_pagamento_cohort,
  -- Coluna AZ: Volume_transcorrido
  -- Lógica exata do Sheets:
  -- SE day_base >= WORKDAY(fim_do_mes + 1, -6) E day_base <= fim_do_mes
  -- E (Data_Pagamento_Cohort é NULL OU mês(AY) = mês(mes_base + 1))
  -- E (dt_cancelado é NULL OU mês(dt_cancelado) <> mês(mes_base))
  -- ENTÃO faturado_mes; SENÃO 0
  CASE
    WHEN b.day_base >= (
           SELECT MIN(d)
           FROM (
             SELECT d
             FROM UNNEST(GENERATE_DATE_ARRAY(DATE_SUB(LAST_DAY(b.mes_base), INTERVAL 15 DAY), LAST_DAY(b.mes_base))) AS d
             WHERE EXTRACT(DAYOFWEEK FROM d) NOT IN (1, 7) -- Filtra 1=Domingo, 7=Sábado
             ORDER BY d DESC
             LIMIT 6 -- Pega os últimos 6 dias úteis e o MIN() garante que é a data de corte inicial
           )
         )
      AND b.day_base <= LAST_DAY(b.mes_base)
      AND (rc.data_pagamento_cohort IS NULL
           OR EXTRACT(MONTH FROM rc.data_pagamento_cohort) = EXTRACT(MONTH FROM DATE_ADD(b.mes_base, INTERVAL 1 MONTH)))
      AND (b.dt_cancelado IS NULL
           OR EXTRACT(MONTH FROM b.dt_cancelado) <> EXTRACT(MONTH FROM b.mes_base)
           OR EXTRACT(YEAR FROM b.dt_cancelado) <> EXTRACT(YEAR FROM b.mes_base))
    THEN b.faturado_mes
    ELSE 0
  END AS volume_transcorrido

FROM base_com_lag b
LEFT JOIN transferencias t
  ON b.advertiser_id = t.advertiser_id
LEFT JOIN desconto_faseado df
  ON CAST(b.advertiser_id AS STRING) = df.advertiser_id
LEFT JOIN `conect-python-g-sheets.planejamento_comercial.radar_cohort` rc
  ON b.advertiser_id = rc.advertiser_id
  AND b.mes_base = rc.mes_base