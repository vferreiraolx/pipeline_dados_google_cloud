-- =============================================================================
-- Extração Trino: desconto_faseado
-- =============================================================================
-- Descrição: Extrai lista de advertiser_ids com desconto faseado do Salesforce,
--            filtrada apenas pelos advertisers que existem na re_gold (RE).
--            Usada na receita_enriquecida como flag "Sim"/"Não".
--
-- Lógica: Traz todas oportunidades com desconto recorrente (discountrecurringvalue)
--         e filtra via LEFT JOIN com re_gold pra manter apenas advertisers de RE.
--
-- Origem (Trino):
--   - hive.cross_salesforce.opportunity
--   - hive.cross_salesforce.account
--   - hive.cross_salesforce.user
--   - hive.planejamento.re_gold_receita_unificado_air (filtro RE)
--
-- Destino BigQuery:
--   - conect-python-g-sheets.planejamento_comercial.desconto_faseado
--
-- Modo de escrita: WRITE_TRUNCATE
-- =============================================================================

WITH max_part AS (
  SELECT MAX(year * 10000 + month * 100 + day) AS max_dt
  FROM hive.cross_salesforce.opportunity
  WHERE year >= YEAR(CURRENT_DATE)
),

-- Advertisers que existem na re_gold (são de Real Estate)
advertisers_re AS (
  SELECT DISTINCT advertiser_id
  FROM hive.planejamento.re_gold_receita_unificado_air
  WHERE dt = (SELECT MAX(dt) FROM hive.planejamento.re_gold_receita_unificado_air)
),

-- Todas oportunidades com desconto
opps_desconto AS (
  SELECT DISTINCT
    a.idorigin__c AS advertiser_id,
    a.name AS nome_conta,
    o.lastmodifieddate AS data_ultima_mudanca_fase,
    o.stagename AS fase,
    CAST(o.amount AS double) AS valor_total,
    CAST(o.recurringtotalvalue__c AS double) AS valor_mensal,
    CAST(o.discountrecurringvalue__c AS double) AS promocao_desconto_3meses,
    o.uniqueopportunityidentifier__c AS id_unico_oportunidade,
    o.leadsource AS origem_lead,
    o.generatedby__c AS gerado_por,
    CAST(o.discountrecurringpercentage__c AS double) AS pct_desconto,
    u.name AS proprietario_oportunidade
  FROM hive.cross_salesforce.opportunity o
  CROSS JOIN max_part mp
  JOIN hive.cross_salesforce.account a
    ON o.accountid = a.id
    AND a.year = CAST(mp.max_dt / 10000 AS integer)
    AND a.month = CAST((mp.max_dt % 10000) / 100 AS integer)
    AND a.day = CAST(mp.max_dt % 100 AS integer)
  LEFT JOIN hive.cross_salesforce."user" u
    ON o.ownerid = u.id
    AND u.year = CAST(mp.max_dt / 10000 AS integer)
    AND u.month = CAST((mp.max_dt % 10000) / 100 AS integer)
    AND u.day = CAST(mp.max_dt % 100 AS integer)
  WHERE o.year = CAST(mp.max_dt / 10000 AS integer)
    AND o.month = CAST((mp.max_dt % 10000) / 100 AS integer)
    AND o.day = CAST(mp.max_dt % 100 AS integer)
    AND o.discountrecurringvalue__c IS NOT NULL
    AND o.discountrecurringvalue__c != '0'
    AND o.discountrecurringvalue__c != '0.0'
    AND a.idorigin__c IS NOT NULL
    AND a.idorigin__c != ''
)

-- Filtrar apenas advertisers que existem na re_gold (Real Estate)
SELECT od.*
FROM opps_desconto od
INNER JOIN advertisers_re re ON od.advertiser_id = re.advertiser_id
