-- =============================================================================
-- Tabela Derivada: receita_consolidada
-- =============================================================================
-- Descrição: Consolida dados de receita da tabela gold unificada com dados de
--            receita CB e planos periódicos, usando colunas reais do schema.
--
-- Tabelas de origem:
--   - conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air
--   - conect-python-g-sheets.planejamento_comercial.re_silver_receita_cb_air
--
-- Modo de escrita: WRITE_TRUNCATE (substituição completa a cada execução)
-- =============================================================================

SELECT
    dt,
    'receita_unificada' AS fonte,
    advertiser_id,
    mes_base,
    canal_conta,
    cordenador,
    estado,
    tamanho,
    classificacao,
    faturado_mes,
    status_ts
FROM `conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air`

UNION ALL

SELECT
    dt,
    'receita_cb' AS fonte,
    advertiser_id,
    mes_base,
    canal_conta,
    dono_conta AS cordenador,
    estado,
    tamanho,
    classificacao,
    pago_mes AS faturado_mes,
    status_ts
FROM `conect-python-g-sheets.planejamento_comercial.re_silver_receita_cb_air`
