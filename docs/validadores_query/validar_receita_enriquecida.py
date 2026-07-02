"""
Validador: receita_enriquecida
Compara totais de faturado e pago do CSV do Sheets vs BigQuery.

Uso:
    python docs/validadores_query/validar_receita_enriquecida.py

Antes de rodar:
    - Exporte a aba "Receita 4.0/SVA" como CSV
    - Atualize o csv_path abaixo
"""
import pandas as pd
from google.cloud import bigquery

# ============ CONFIGURAR ============
csv_path = r"C:\Users\vinicius.foreste\Downloads\Dados Receita 4.0 - Receita 4.0_SVA (2).csv"
mes_filtro = "01/06/2026"  # Formato do CSV
mes_bq = "2026-06-01"      # Formato BigQuery
# ====================================

# Ler CSV
df = pd.read_csv(csv_path, encoding='utf-8', low_memory=False, decimal=',', thousands='.')
jun_csv = df[df['mes_base'] == mes_filtro]

# Consultar BQ
client = bigquery.Client(project="conect-python-g-sheets")
query = f"""
SELECT
    ROUND(SUM(faturado_mes), 2) as faturado_mes,
    ROUND(SUM(COALESCE(pago_mes_campanha,0)), 2) as pago_mes_campanha,
    ROUND(SUM(COALESCE(pago_mes_bairro,0)), 2) as pago_mes_bairro,
    ROUND(SUM(COALESCE(pago_mes_topo,0)), 2) as pago_mes_topo,
    ROUND(SUM(COALESCE(faturado_mes_campanha,0)), 2) as faturado_mes_campanha,
    ROUND(SUM(COALESCE(faturado_mes_bairro_vip,0)), 2) as faturado_mes_bairro_vip,
    ROUND(SUM(COALESCE(faturado_mes_topo_fixo,0)), 2) as faturado_mes_topo_fixo
FROM conect-python-g-sheets.planejamento_comercial.receita_enriquecida
WHERE mes_base = '{mes_bq}'
"""
bq_result = client.query(query).to_dataframe().iloc[0]

# Comparar
print(f"{'Coluna':<25} {'CSV Sheets':>15} {'BigQuery':>15} {'Match':>6}")
print("-" * 65)

colunas = ['faturado_mes', 'pago_mes_campanha', 'pago_mes_bairro', 'pago_mes_topo',
           'faturado_mes_campanha', 'faturado_mes_bairro_vip', 'faturado_mes_topo_fixo']

for col in colunas:
    csv_val = jun_csv[col].sum()
    bq_val = bq_result[col]
    match = "✅" if abs(csv_val - bq_val) < 0.01 else "❌"
    print(f"{col:<25} {csv_val:>15,.2f} {bq_val:>15,.2f} {match:>6}")
