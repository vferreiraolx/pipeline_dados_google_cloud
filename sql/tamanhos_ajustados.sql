-- =============================================================================
-- Tabela Derivada: tamanhos_ajustados
-- =============================================================================
-- Descrição: Replica a aba "Tamanhos ajustados" do Sheets - compara tamanho
--            ajustado do mês atual com o mês anterior pra cada advertiser.
--            Indica se mudou (status_tamanho) e sugere o tamanho correto.
--
-- Dependência:
--   - conect-python-g-sheets.planejamento_comercial.receita_enriquecida
--
-- Modo de escrita: WRITE_TRUNCATE
-- =============================================================================

WITH com_anterior AS (
  SELECT
    advertiser_id,
    mes_base,
    tamanho_ajustado AS tamanho_atual,
    LAG(tamanho_ajustado) OVER (PARTITION BY advertiser_id ORDER BY mes_base) AS tamanho_mes_anterior
  FROM `conect-python-g-sheets.planejamento_comercial.receita_enriquecida`
)

SELECT
  advertiser_id,
  mes_base,
  tamanho_atual,
  tamanho_mes_anterior,
  CASE
    WHEN tamanho_mes_anterior IS NULL THEN 'Novo'
    WHEN tamanho_atual = tamanho_mes_anterior THEN 'OK'
    ELSE 'Mudou'
  END AS status_tamanho,
  -- Tamanho correto sugerido: mantém o atual (lógica simplificada)
  tamanho_atual AS tamanho_correto_sugerido
FROM com_anterior
WHERE tamanho_mes_anterior IS NOT NULL
ORDER BY advertiser_id, mes_base
