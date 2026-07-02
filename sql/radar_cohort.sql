-- =============================================================================
-- Extração Trino: radar_cohort
-- =============================================================================
-- Descrição: Extrai APENAS as colunas de cohort (vencimento e pagamento)
--            da re_bronze_radar pra enriquecer a receita_enriquecida.
--            Volume mínimo: só advertiser_id, mes derivado, e 2 datas.
--
-- Origem (Trino):
--   - hive.planejamento.re_bronze_radar (snapshot MAX(dt))
--
-- Destino BigQuery:
--   - conect-python-g-sheets.planejamento_comercial.radar_cohort
--
-- Modo de escrita: WRITE_TRUNCATE
-- =============================================================================

SELECT
  advertiser_id,
  DATE_TRUNC('month', base_date) AS mes_base,
  expiration_date AS data_vencimento_cohort,
  payment_date AS data_pagamento_cohort
FROM hive.planejamento.re_bronze_radar
WHERE dt = (SELECT MAX(dt) FROM hive.planejamento.re_bronze_radar)
  AND base_date IS NOT NULL