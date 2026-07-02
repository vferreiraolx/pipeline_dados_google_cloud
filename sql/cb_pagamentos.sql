-- =============================================================================
-- Tabela Derivada: cb_pagamentos
-- =============================================================================
-- Descrição: Consolida dados de pagamentos CB, enriquecendo informações de
--            pagamento com dados de coordenador, canal, estado e tamanho
--            a partir da receita unificada.
--
-- Tabelas de origem:
--   - conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air
--   - conect-python-g-sheets.planejamento_comercial.re_silver_receita_cb_paids_air
--
-- Modo de escrita: WRITE_TRUNCATE (substituição completa a cada execução)
-- =============================================================================

WITH dados AS (
SELECT
    advertiser_id,
    mes_base,
    canal_conta,
    cordenador,
    estado,
    tamanho,
    municipio,
    classificacao,
    /*CASE 
        -- Verifica se o estado está vazio ou nulo
        WHEN canal_conta = 'Field' and (estado IS NULL OR estado = '') THEN ''
        WHEN canal_conta = 'Field' and (estado IN ('RS', 'SC', 'PR')) THEN 'Sul'
        WHEN canal_conta = 'Field' and (estado IN ('MG', 'ES')) THEN 'MG/ES'
        WHEN canal_conta = 'Field' and (estado = 'RJ') THEN 'RJ'
        WHEN canal_conta = 'Field' and (estado IN ('MS', 'MT', 'GO', 'DF', 'TO', 'PA', 'AP', 'RO', 'AC', 'AM')) THEN 'NO/CO'
        WHEN canal_conta = 'Field' and (estado IN ('BA', 'PI', 'MA', 'CE', 'RN', 'PB', 'PE', 'AL', 'SE')) THEN 'NE'
        WHEN canal_conta = 'Field' and (estado = 'SP' AND municipio = 'São Paulo') THEN 'Sp Capital'
        WHEN canal_conta = 'Field' and (estado = 'SP' AND municipio <> 'São Paulo') THEN 'SP Interior & Litoral'
        --Inside
		WHEN canal_conta = 'Inside' AND estado IN ('RJ', 'MG', 'ES') THEN 'RJ+MG+ES'
		WHEN canal_conta = 'Inside' AND estado IN (
        'GO', 'BA', 'PB', 'PE', 'CE', 'DF', 'MS', 'MT', 'AL', 'MA', 
        'PI', 'RN', 'SE', 'AC', 'AM', 'AP', 'PA', 'RO', 'RR', 'TO'
    	) THEN 'N+NE+CO'
    	WHEN canal_conta = 'Inside' AND estado IN ('SC', 'PR', 'RS') THEN 'Sul+SP Interior'
    -- 2. Regras específicas para SP (Capital vs Interior/Sul)
    	WHEN canal_conta = 'Inside' AND estado = 'SP' THEN 
        	CASE 
            	WHEN municipio IN (
                'São Paulo', 'SAO PAULO', 'Guarulhos', 'Arujá', 'Caieiras', 
                'Mogi das Cruzes', 'Osasco', 'Santana de Parnaíba', 'Santo André', 
                'Suzano', 'Cajamar', 'Diadema', 'Jandira', 'Mairiporã', 'Barueri', 
                'São Caetano do Sul', 'Embu das Artes', 'São Bernardo Do Campo', 
                'SAO BERNARDO DO CAMPO', 'Taboão da Serra', 'Mauá', 'Cotia', 
                'Guararema', 'Franco da Rocha', 'Carapicuíba', 'Ferraz de Vasconcelos', 
                'Juquitiba', 'Poá', 'Itaquaquecetuba', 'Itapecerica da Serra', 
                'Santa Isabel', 'Ribeirão Pires', 'Vargem Grande Paulista', 
                'Biritiba-Mirim', 'Itapevi', 'Embu-Guaçu'
            	) THEN 'SP Capital'
            	ELSE 'Sul+SP Interior'
        	END
        ELSE 'Outros'
    END AS regionalizacao,*/
    CASE
      WHEN estado IS NULL OR TRIM(CAST(estado AS STRING)) = '' THEN ''
      WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(estado AS STRING))), r'^(RS|SC|PR)$') THEN 'Sul'
      WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(estado AS STRING))), r'^(MG|ES)$') THEN 'MG/ES'
      WHEN UPPER(TRIM(CAST(estado AS STRING))) = 'RJ' THEN 'RJ'
      WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(estado AS STRING))), r'^(MS|MT|GO|DF|TO|PA|AP|RO|AC|AM)$') THEN 'NO/CO'
      WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(estado AS STRING))), r'^(BA|PI|MA|CE|RN|PB|PE|AL|SE)$') THEN 'NE'
      WHEN UPPER(TRIM(CAST(estado AS STRING))) = 'SP' AND UPPER(TRIM(CAST(municipio AS STRING))) = 'SÃO PAULO' THEN 'Sp Capital'
      WHEN UPPER(TRIM(CAST(estado AS STRING))) = 'SP' AND (municipio IS NULL OR UPPER(TRIM(CAST(municipio AS STRING))) <> 'SÃO PAULO') THEN 'SP Interior & Litoral'
      ELSE 'Outros'
    END AS regionalizacao,
      CASE
      WHEN classificacao <> 'Novo'
      AND LAG(canal_conta, 1, 'inicio') OVER (PARTITION BY advertiser_id ORDER BY mes_base) <> canal_conta
      THEN 'Migrado'
      ELSE NULL
    END AS status_migrado,
case when classificacao <> 'Novo' and LAG(canal_conta, 1, 'inicio') OVER (PARTITION BY advertiser_id ORDER by mes_base) <> canal_conta then LAG(canal_conta, 1, 'inicio') OVER (PARTITION BY advertiser_id ORDER by mes_base) else null end as aux_canal_out,
case when classificacao <> 'Novo' and LAG(canal_conta, 1, 'inicio') OVER (PARTITION BY advertiser_id ORDER by mes_base) <> canal_conta then LAG(cordenador, 1, 'inicio') OVER (PARTITION BY advertiser_id ORDER by mes_base) else null end as aux_coord_out
FROM `conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air`
),

-- Lista de TODOS os advertisers que já migraram pro Field (a partir de dez/2025)
transferencias_historico AS (
  SELECT DISTINCT advertiser_id
  FROM dados
  WHERE status_migrado = 'Migrado' AND canal_conta = 'Field'
    AND mes_base >= DATE '2025-12-01'
),

dados_rank AS (
  SELECT
    d.*,
    ROW_NUMBER() OVER (PARTITION BY advertiser_id ORDER BY mes_base DESC) AS rnk_ult
  FROM dados d
),

paids AS (
  SELECT
    p.*,
    CAST(COALESCE(p.antecipado, 0) AS NUMERIC) AS antecipado_calc,
    CAST(COALESCE(p.no_mes, 0) AS NUMERIC) AS no_mes_calc,
    CAST(COALESCE(p.transcorrido, 0) AS NUMERIC) AS transcorrido_calc,
    CAST(COALESCE(p.antecipado, 0) + COALESCE(p.no_mes, 0) + COALESCE(p.transcorrido, 0) AS NUMERIC) AS pago_mes_calc
  FROM `conect-python-g-sheets.planejamento_comercial.re_silver_receita_cb_paids_air` p
  WHERE p.dt = (SELECT MAX(dt) FROM `conect-python-g-sheets.planejamento_comercial.re_silver_receita_cb_paids_air`)
),

enriched AS (
  SELECT
    p.advertiser_id,
    p.mes_pago,
    p.status_ts,
    p.antecipado_calc,
    p.no_mes_calc,
    p.transcorrido_calc,
    p.pago_mes_calc,
    p.day_paid,
    p.dt,
    COALESCE(NULLIF(c.cordenador, ""), c.canal_conta) AS coordenador,
    c.canal_conta AS canal,
    CONCAT(
      CAST(p.advertiser_id AS STRING),
      CAST(DATE_DIFF(
        COALESCE(SAFE.PARSE_DATE("%d/%m/%Y", CAST(p.mes_pago AS STRING)), SAFE_CAST(p.mes_pago AS DATE)),
        DATE "1899-12-30",
        DAY
      ) AS STRING)
    ) AS id_data,
    c.estado,
    c.regionalizacao AS regionalizacao,
    c.aux_canal_out,
    c.aux_coord_out,
    c.tamanho,
    coalesce(c.status_migrado, "Não") as status_migrado,
    CASE
      WHEN c.canal_conta = "Field"
      AND p.advertiser_id IN (SELECT advertiser_id FROM transferencias_historico)
      THEN "Sim"
      ELSE "Não"
    END AS id_migracao_pro_field,
    c.estado AS uf,
    --COALESCE(NULLIF(c.cordenador, ""), c.canal_conta) AS coordenador_ajustado,
    CASE WHEN 
      c.canal_conta IN ("Online","ND") then c.canal_conta
      ELSE COALESCE(UPPER(TRIM(c.cordenador)), "")
      END AS coordenador_ajustado,
    ROW_NUMBER() OVER (
      PARTITION BY p.advertiser_id, p.mes_pago
      ORDER BY CASE WHEN c.mes_base = p.mes_pago THEN 1 ELSE 2 END, c.mes_base DESC
    ) AS rnk_desempate
  FROM paids p
  LEFT JOIN dados_rank c
    ON p.advertiser_id = c.advertiser_id
    AND (c.mes_base = p.mes_pago OR c.rnk_ult = 1)
)

SELECT
  advertiser_id,
  FORMAT_DATE("%d/%m/%Y", COALESCE(SAFE.PARSE_DATE("%d/%m/%Y", CAST(mes_pago AS STRING)), SAFE_CAST(mes_pago AS DATE))) AS mes_pago,
  FORMAT_DATE("%d/%m/%Y", COALESCE(SAFE.PARSE_DATE("%d/%m/%Y", CAST(day_paid AS STRING)), SAFE_CAST(day_paid AS DATE))) AS day_paid,
  status_ts,
  antecipado_calc AS antecipado,
  no_mes_calc AS no_mes,
  transcorrido_calc AS transcorrido,
  pago_mes_calc AS pago_mes,
  FORMAT_DATE("%d/%m/%Y", COALESCE(SAFE.PARSE_DATE("%d/%m/%Y", CAST(dt AS STRING)), SAFE_CAST(dt AS DATE))) AS dt,
  coordenador,
  canal,
  id_data AS id_e_data,
  regionalizacao,
  uf,
  tamanho,
  status_migrado,
  id_migracao_pro_field,
  coordenador_ajustado,
  aux_canal_out,
  aux_coord_out
FROM enriched
WHERE rnk_desempate = 1 
and mes_pago IN (DATE_TRUNC(CURRENT_DATE(), MONTH),DATE_SUB(DATE_TRUNC(CURRENT_DATE(), MONTH), INTERVAL 1 MONTH)
) 
ORDER BY
  COALESCE(SAFE.PARSE_DATE("%d/%m/%Y", CAST(mes_pago AS STRING)), SAFE_CAST(mes_pago AS DATE)) DESC,
  advertiser_id