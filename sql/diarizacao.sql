-- =============================================================================
-- Tabela Derivada: diarizacao
-- =============================================================================
-- Descrição: Replica a aba "Diarização" do Sheets - pivot diário de receita
--            por classificação e canal. Cada linha = 1 dia, colunas = NOVO/CHURN/
--            UPGRADE/DOWNGRADE cruzado com Field/Inside/Online/ND.
--
-- Lógica das fórmulas:
--   NOVO:      SUMIFS(faturado_mes; day_base = data; classificacao = "Novo"; canal_conta = canal)
--   CHURN:     SUMIFS(faturado_mes; day_churn = data; classificacao_churn = "CHURN"; canal_conta = canal)
--   UPGRADE:   SUMIFS(delta; day_base = data; classificacao = "Upgrade"; canal_conta = canal)
--   DOWNGRADE: SUMIFS(delta; day_base = data; classificacao = "Downgrade"; canal_conta = canal)
--
-- Dependência:
--   - conect-python-g-sheets.planejamento_comercial.receita_enriquecida
--
-- Modo de escrita: WRITE_TRUNCATE (substituição completa a cada execução)
-- =============================================================================

WITH r AS (
  SELECT * FROM `conect-python-g-sheets.planejamento_comercial.receita_enriquecida`
),

-- Gerar todas as datas distintas de day_base e day_churn
datas AS (
  SELECT DISTINCT day_base AS dia FROM r WHERE day_base IS NOT NULL
  UNION DISTINCT
  SELECT DISTINCT day_churn AS dia FROM r WHERE day_churn IS NOT NULL
)

SELECT
  d.dia AS Mes,

  -- NOVO (SUMIFS faturado_mes onde day_base = dia AND classificacao = 'Novo')
  ROUND(COALESCE(SUM(CASE WHEN r.day_base = d.dia AND r.classificacao = 'Novo' AND r.canal_conta = 'Field' THEN r.faturado_mes END), 0), 0) AS novo_field,
  ROUND(COALESCE(SUM(CASE WHEN r.day_base = d.dia AND r.classificacao = 'Novo' AND r.canal_conta = 'Inside' THEN r.faturado_mes END), 0), 0) AS novo_inside,
  ROUND(COALESCE(SUM(CASE WHEN r.day_base = d.dia AND r.classificacao = 'Novo' AND r.canal_conta = 'Online' THEN r.faturado_mes END), 0), 0) AS novo_online,
  ROUND(COALESCE(SUM(CASE WHEN r.day_base = d.dia AND r.classificacao = 'Novo' AND r.canal_conta = 'ND' THEN r.faturado_mes END), 0), 0) AS novo_nd,

  -- CHURN (SUMIFS faturado_mes onde day_churn = dia AND classificacao_churn = 'CHURN')
  ROUND(COALESCE(SUM(CASE WHEN r.day_churn = d.dia AND r.classificacao_churn = 'CHURN' AND r.canal_conta = 'Field' THEN r.faturado_mes END), 0), 0) AS churn_field,
  ROUND(COALESCE(SUM(CASE WHEN r.day_churn = d.dia AND r.classificacao_churn = 'CHURN' AND r.canal_conta = 'Inside' THEN r.faturado_mes END), 0), 0) AS churn_inside,
  ROUND(COALESCE(SUM(CASE WHEN r.day_churn = d.dia AND r.classificacao_churn = 'CHURN' AND r.canal_conta = 'Online' THEN r.faturado_mes END), 0), 0) AS churn_online,
  ROUND(COALESCE(SUM(CASE WHEN r.day_churn = d.dia AND r.classificacao_churn = 'CHURN' AND r.canal_conta = 'ND' THEN r.faturado_mes END), 0), 0) AS churn_nd,

  -- UPGRADE (SUMIFS delta onde day_base = dia AND classificacao = 'Upgrade')
  ROUND(COALESCE(SUM(CASE WHEN r.day_base = d.dia AND r.classificacao = 'Upgrade' AND r.canal_conta = 'Field' THEN r.delta END), 0), 0) AS upgrade_field,
  ROUND(COALESCE(SUM(CASE WHEN r.day_base = d.dia AND r.classificacao = 'Upgrade' AND r.canal_conta = 'Inside' THEN r.delta END), 0), 0) AS upgrade_inside,
  ROUND(COALESCE(SUM(CASE WHEN r.day_base = d.dia AND r.classificacao = 'Upgrade' AND r.canal_conta = 'Online' THEN r.delta END), 0), 0) AS upgrade_online,
  ROUND(COALESCE(SUM(CASE WHEN r.day_base = d.dia AND r.classificacao = 'Upgrade' AND r.canal_conta = 'ND' THEN r.delta END), 0), 0) AS upgrade_nd,

  -- DOWNGRADE (SUMIFS delta onde day_base = dia AND classificacao = 'Downgrade')
  ROUND(COALESCE(SUM(CASE WHEN r.day_base = d.dia AND r.classificacao = 'Downgrade' AND r.canal_conta = 'Field' THEN r.delta END), 0), 0) AS downgrade_field,
  ROUND(COALESCE(SUM(CASE WHEN r.day_base = d.dia AND r.classificacao = 'Downgrade' AND r.canal_conta = 'Inside' THEN r.delta END), 0), 0) AS downgrade_inside,
  ROUND(COALESCE(SUM(CASE WHEN r.day_base = d.dia AND r.classificacao = 'Downgrade' AND r.canal_conta = 'Online' THEN r.delta END), 0), 0) AS downgrade_online,
  ROUND(COALESCE(SUM(CASE WHEN r.day_base = d.dia AND r.classificacao = 'Downgrade' AND r.canal_conta = 'ND' THEN r.delta END), 0), 0) AS downgrade_nd,

  -- dia (auxiliar para filtros no Sheets)
  EXTRACT(DAY FROM d.dia) AS dia_numero

FROM datas d
LEFT JOIN r ON (r.day_base = d.dia OR r.day_churn = d.dia)
GROUP BY d.dia
ORDER BY d.dia DESC
