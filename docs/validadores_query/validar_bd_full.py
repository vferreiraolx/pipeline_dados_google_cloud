"""
Validador: bd_full
Compara contagens e valores agregados por Canal do CSV vs BigQuery.

Uso:
    python docs/validadores_query/validar_bd_full.py
"""
import pandas as pd
from google.cloud import bigquery

# ============ CONFIGURAR ============
csv_path = r"C:\Users\vinicius.foreste\Downloads\Dados Receita 4.0 - BD FULL (2).csv"
mes_filtro = "01/06/2026"
mes_bq = "2026-06-01"
# ====================================

# Ler CSV (header na linha 4, dados a partir da linha 5)
df = pd.read_csv(csv_path, encoding='utf-8', header=3, low_memory=False, decimal=',', thousands='.')
df = df.loc[:, ~df.columns.str.startswith('Unnamed')]
jun_csv = df[df['Mes Base'] == mes_filtro]

# Totais CSV por Canal
csv_totais = jun_csv.groupby('Canal').agg({
    '# Base Inicial': 'sum',
    '# Novos': 'sum',
    '# Churn': 'sum',
}).reset_index()

# Consultar BQ
client = bigquery.Client(project="conect-python-g-sheets")
query = f"""
SELECT Canal,
    SUM(base_inicial_qtd) as base_ini,
    SUM(novos_qtd) as novos,
    SUM(churn_qtd) as churn
FROM conect-python-g-sheets.planejamento_comercial.bd_full
WHERE Mes_Base = '{mes_bq}'
GROUP BY Canal
ORDER BY Canal
"""
bq_result = client.query(query).to_dataframe()

print(f"{'Canal':<10} {'Métrica':<15} {'CSV':>10} {'BQ':>10} {'Diff':>8}")
print("-" * 55)

for _, row in csv_totais.iterrows():
    canal = row['Canal']
    bq_row = bq_result[bq_result['Canal'] == canal]
    if len(bq_row) > 0:
        bq_row = bq_row.iloc[0]
        for col_csv, col_bq in [('# Base Inicial', 'base_ini'), ('# Novos', 'novos'), ('# Churn', 'churn')]:
            csv_val = row[col_csv]
            bq_val = bq_row[col_bq]
            diff = bq_val - csv_val
            print(f"{canal:<10} {col_csv:<15} {csv_val:>10} {bq_val:>10} {diff:>8}")
