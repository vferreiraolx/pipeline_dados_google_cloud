-- =============================================================================
-- Tabela Derivada: planos_periodicos
-- =============================================================================
-- Descrição: Query de planos periódicos com delta MoM, classificação
--            Upgrade/Downgrade, tamanho oficial e regionalização.
--
-- Dependência:
--   - conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb
--
-- Modo de escrita: WRITE_TRUNCATE (substituição completa a cada execução)
-- =============================================================================

WITH planos AS (
  SELECT
    *,
    -- Regionalização (apenas por estado/cidade, sem condicionar ao canal)
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
      WHEN UPPER(TRIM(CAST(canal AS STRING))) IN ('ONLINE', 'ND') THEN ''
      ELSE UPPER(TRIM(COALESCE(CAST(coordenador_conta AS STRING), '')))
    END AS equipe_ajustada,
    -- Delta MoM particionado por id_conta_olx + id_contrato
    valor_mensal - LAG(valor_mensal) OVER (PARTITION BY id_conta_olx, id_contrato ORDER BY competencia) AS delta,
    -- Número extraído do package_name para tamanho_oficial
    SAFE_CAST(REGEXP_EXTRACT(package_name, r'(\d+)') AS INT64) AS numero_pacote
  FROM `conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb`
  WHERE dt = (SELECT MAX(dt) FROM `conect-python-g-sheets.planejamento_comercial.re_silver_planos_periodicos_cb`)
)

SELECT
  *,
  -- classifica_up
  CASE
    WHEN delta > 0 THEN 'Upgrade'
    WHEN delta < 0 THEN 'Downgrade'
    ELSE NULL
  END AS classifica_up,
  -- tamanho_oficial
  CASE
    WHEN numero_pacote <= 25 OR numero_pacote IS NULL THEN 'PP'
    WHEN numero_pacote <= 80 THEN 'P'
    WHEN numero_pacote <= 600 THEN 'M'
    ELSE 'G'
  END AS tamanho_oficial
FROM planos
