"""
Validador: diarizacao
Compara pivot diário do CSV vs BigQuery.

Uso:
    python docs/validadores_query/validar_diarizacao.py
"""
import pandas as pd
from google.cloud import bigquery

# ============ CONFIGURAR ============
csv_path = r"C:\Users\vinicius.foreste\Downloads\Dados Receita 4.0 - Diarização (1).csv"
data_teste = "2026-06-02"
# ====================================

# Ler CSV (3 linhas de header)
df = pd.read_csv(csv_path, encoding='utf-8', header=None, skiprows=3, low_memory=False, decimal=',', thousands='.')
df.columns = ['Mes','novo_field','novo_inside','novo_online','novo_nd','sep1',
              'churn_field','churn_inside','churn_online','churn_nd','sep2',
              'upgrade_field','upgrade_inside','upgrade_online','upgrade_nd','sep3',
              'downgrade_field','downgrade_inside','downgrade_online','downgrade_nd','sep4','dia']
df['Mes'] = pd.to_datetime(df['Mes'], format='%Y-%m-%d', errors='coerce')

num_cols = ['novo_field','novo_inside','novo_online','novo_nd',
            'churn_field','churn_inside','churn_online','churn_nd',
            'upgrade_field','upgrade_inside','upgrade_online','upgrade_nd',
            'downgrade_field','downgrade_inside','downgrade_online','downgrade_nd']
for c in num_cols:
    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

csv_row = df[df['Mes'] == data_teste].iloc[0] if len(df[df['Mes'] == data_teste]) > 0 else None

# Consultar BQ
client = bigquery.Client(project="conect-python-g-sheets")
query = f"""
SELECT * FROM conect-python-g-sheets.planejamento_comercial.diarizacao
WHERE Mes = '{data_teste}'
"""
bq_row = client.query(query).to_dataframe().iloc[0]

print(f"Data: {data_teste}")
print(f"{'Coluna':<20} {'CSV':>12} {'BQ':>12} {'Match':>6}")
print("-" * 55)

for col in num_cols:
    csv_val = csv_row[col] if csv_row is not None else 0
    bq_val = round(bq_row[col], 0)
    match = "✅" if abs(csv_val - bq_val) < max(abs(csv_val) * 0.05, 1) else "⚠️"
    print(f"{col:<20} {csv_val:>12,.0f} {bq_val:>12,.0f} {match:>6}")
