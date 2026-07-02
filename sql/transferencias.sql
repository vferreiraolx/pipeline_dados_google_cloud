-- =============================================================================
-- Tabela Derivada: transferencias
-- =============================================================================
-- Descrição: Replica a aba "Transferências" do Sheets - lista de advertisers
--            que migraram de canal (status_migrado = 'Migrado').
--            Derivada da re_gold via LAG pra detectar mudança de canal_conta.
--
-- Dependência:
--   - conect-python-g-sheets.planejamento_comercial.receita_enriquecida
--
-- Modo de escrita: WRITE_TRUNCATE
-- =============================================================================

SELECT
  advertiser_id,
  mes_base,
  tamanho_ajustado AS tamanho,
  canal_conta,
  status_migrado,
  aux_canal_out
FROM `conect-python-g-sheets.planejamento_comercial.receita_enriquecida`
WHERE status_migrado = 'Migrado'
  AND canal_conta = 'Field'
ORDER BY mes_base DESC, advertiser_id
