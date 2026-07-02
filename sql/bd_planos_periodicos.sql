-- =============================================================================
-- Tabela Derivada: bd_planos_periodicos
-- =============================================================================
-- Descrição: Replica a aba "BD Planos Periódicos" do Sheets.
--            Agrega por Canal, Equipe, Regiao_Macro, Mes Base, Tamanho.
--            Inclui colunas: delta (MoM), classifica_up, tamanho_oficial.
--
-- Dependência:
--   - conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb
--
-- Modo de escrita: WRITE_TRUNCATE (substituição completa a cada execução)
-- =============================================================================

WITH planos AS (
  SELECT
    *,
    -- Regionalização (mesma lógica para todos os canais)
    CASE 
      WHEN estado_conta IS NULL OR TRIM(CAST(estado_conta AS STRING)) = '' THEN ''
      WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(estado_conta AS STRING))), r'^(RS|SC|PR)$') THEN 'Sul'
      WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(estado_conta AS STRING))), r'^(MG|ES)$') THEN 'MG/ES'
      WHEN UPPER(TRIM(CAST(estado_conta AS STRING))) = 'RJ' THEN 'RJ'
      WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(estado_conta AS STRING))), r'^(MS|MT|GO|DF|TO|PA|AP|RO|AC|AM)$') THEN 'NO/CO'
      WHEN REGEXP_CONTAINS(UPPER(TRIM(CAST(estado_conta AS STRING))), r'^(BA|PI|MA|CE|RN|PB|PE|AL|SE)$') THEN 'NE'
      WHEN UPPER(TRIM(CAST(estado_conta AS STRING))) = 'SP' AND UPPER(TRIM(CAST(cidade_conta AS STRING))) = 'SÃO PAULO' THEN 'Sp Capital'
      WHEN UPPER(TRIM(CAST(estado_conta AS STRING))) = 'SP' AND (cidade_conta IS NULL OR UPPER(TRIM(CAST(cidade_conta AS STRING))) <> 'SÃO PAULO') THEN 'SP Interior & Litoral'
      ELSE 'Outros'
    END AS regionalizacao,
    -- Equipe ajustada
    CASE
      WHEN UPPER(TRIM(CAST(canal AS STRING))) = 'ONLINE' THEN 'Online'
      WHEN UPPER(TRIM(CAST(canal AS STRING))) = 'ND' THEN 'ND'
      ELSE UPPER(TRIM(COALESCE(CAST(coordenador_conta AS STRING), '')))
    END AS equipe_ajustada,
    -- Extrai número do package_name para tamanho_oficial
    SAFE_CAST(REGEXP_EXTRACT(package_name, r'(\d+)') AS INT64) AS numero_pacote,
    -- Delta MoM: valor_mensal atual - valor_mensal do mês anterior (mesmo advertiser)
    valor_mensal - LAG(valor_mensal) OVER (PARTITION BY id_conta_olx ORDER BY competencia) AS delta
  FROM `conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb`
  WHERE dt = (SELECT MAX(dt) FROM `conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb`)
),

planos_enriquecido AS (
  SELECT
    *,
    -- classifica_up baseado no delta
    CASE
      WHEN delta > 0 THEN 'Upgrade'
      WHEN delta < 0 THEN 'Downgrade'
      ELSE NULL
    END AS classifica_up,
    -- tamanho_oficial baseado no número extraído do package_name
    CASE
      WHEN numero_pacote IS NULL THEN NULL
      WHEN numero_pacote <= 25 THEN 'PP'
      WHEN numero_pacote <= 80 THEN 'P'
      WHEN numero_pacote <= 600 THEN 'M'
      ELSE 'G'
    END AS tamanho_oficial
  FROM planos
),

dimensoes AS (
  SELECT DISTINCT
    canal AS Canal,
    equipe_ajustada AS Equipe,
    regionalizacao AS Regiao_Macro,
    competencia AS Mes_Base,
    tamanho AS Tamanho
  FROM planos_enriquecido
  WHERE canal IS NOT NULL AND canal <> ''
    AND competencia IS NOT NULL
)

SELECT
  d.Canal,
  d.Equipe,
  d.Regiao_Macro,
  d.Mes_Base,
  d.Tamanho,

  -- G: # Base Inicial (contratos distintos do mês anterior excluindo churns)
  (SELECT COUNT(DISTINCT CONCAT(id_conta_olx, id_contrato)) FROM planos_enriquecido
   WHERE competencia = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND canal = d.Canal
     AND equipe_ajustada = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND (mes_churn IS NULL OR CAST(mes_churn AS DATE) <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
  ) AS base_inicial_qtd,

  -- H: # Novos
  (SELECT COUNT(DISTINCT CONCAT(id_conta_olx, id_contrato)) FROM planos_enriquecido
   WHERE competencia = d.Mes_Base
     AND canal = d.Canal
     AND equipe_ajustada = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND status_recorrente = 'Novo'
  ) AS novos_qtd,

  -- I: # Churn (*-1)
  (SELECT COUNT(DISTINCT CONCAT(id_conta_olx, id_contrato)) FROM planos_enriquecido
   WHERE CAST(mes_churn AS DATE) = d.Mes_Base
     AND canal = d.Canal
     AND equipe_ajustada = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND status_recorrente = 'Churn'
  ) * -1 AS churn_qtd,

  -- K: $ Base Inicial
  (SELECT COALESCE(SUM(valor_mensal), 0) FROM planos_enriquecido
   WHERE competencia = DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH)
     AND canal = d.Canal
     AND equipe_ajustada = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND (mes_churn IS NULL OR CAST(mes_churn AS DATE) <> DATE_SUB(d.Mes_Base, INTERVAL 1 MONTH))
  ) AS base_inicial_valor,

  -- L: $ Novos
  (SELECT COALESCE(SUM(valor_mensal), 0) FROM planos_enriquecido
   WHERE competencia = d.Mes_Base
     AND canal = d.Canal
     AND equipe_ajustada = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND status_recorrente = 'Novo'
  ) AS novos_valor,

  -- M: $ Upgrade (soma dos deltas positivos)
  (SELECT COALESCE(SUM(delta), 0) FROM planos_enriquecido
   WHERE competencia = d.Mes_Base
     AND canal = d.Canal
     AND equipe_ajustada = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND classifica_up = 'Upgrade'
  ) AS up_valor,

  -- N: $ Downgrade (soma dos deltas negativos)
  (SELECT COALESCE(SUM(delta), 0) FROM planos_enriquecido
   WHERE competencia = d.Mes_Base
     AND canal = d.Canal
     AND equipe_ajustada = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND classifica_up = 'Downgrade'
  ) AS down_valor,

  -- O: $ Churn (*-1)
  (SELECT COALESCE(SUM(valor_mensal), 0) FROM planos_enriquecido
   WHERE CAST(mes_churn AS DATE) = d.Mes_Base
     AND canal = d.Canal
     AND equipe_ajustada = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND status_recorrente = 'Churn'
  ) * -1 AS churn_valor,

  -- # Upgrade
  (SELECT COUNT(DISTINCT CONCAT(id_conta_olx, id_contrato)) FROM planos_enriquecido
   WHERE competencia = d.Mes_Base
     AND canal = d.Canal
     AND equipe_ajustada = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND classifica_up = 'Upgrade'
  ) AS up_qtd,

  -- # Downgrade
  (SELECT COUNT(DISTINCT CONCAT(id_conta_olx, id_contrato)) FROM planos_enriquecido
   WHERE competencia = d.Mes_Base
     AND canal = d.Canal
     AND equipe_ajustada = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND classifica_up = 'Downgrade'
  ) AS down_qtd,

  -- Y: $ Pagamentos no mês (status = 'PAID')
  (SELECT COALESCE(SUM(valor_mensal), 0) FROM planos_enriquecido
   WHERE competencia = d.Mes_Base
     AND canal = d.Canal
     AND equipe_ajustada = d.Equipe
     AND regionalizacao = d.Regiao_Macro
     AND tamanho = d.Tamanho
     AND status = 'PAID'
  ) AS pagamentos_no_mes_valor,

  -- AT: CHAVE CRUZAMENTO
  CONCAT(d.Canal, d.Equipe, d.Regiao_Macro, d.Tamanho) AS chave_cruzamento

FROM dimensoes d
WHERE d.Regiao_Macro IS NOT NULL AND d.Regiao_Macro <> ''
  AND d.Tamanho IS NOT NULL AND d.Tamanho <> ''
ORDER BY d.Mes_Base DESC, d.Canal, d.Equipe
