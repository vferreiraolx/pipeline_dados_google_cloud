"""
Validador legado de snapshot.

O caminho suportado para atualização do BQ é o Cloud Function com VPC.
Este script permanece apenas para inspeções manuais em ambientes legados.
"""
import os, sys
sys.path.insert(0, r'C:\Users\vinicius.foreste\Desktop\Oswaldo_novo\trino_connector\src')
from dotenv import load_dotenv
load_dotenv(r'C:\Users\vinicius.foreste\Desktop\Oswaldo_novo\trino_connector\.env')
from trino_connector.credenciais import load_credentials
from trino_connector.trino_connect import TrinoClient
from google.cloud import bigquery

# Conectar Trino
user, pwd = load_credentials()
client = TrinoClient(host='trino-gateway.dataeng.bigdata.olxbr.io', timeout=120, max_retries=1)
client.connect(user, pwd)

# Verificar MAX(dt) no Trino
df = client.execute("SELECT MAX(dt) as max_dt, COUNT(*) as total FROM hive.planejamento.re_gold_receita_unificado_air WHERE dt = (SELECT MAX(dt) FROM hive.planejamento.re_gold_receita_unificado_air)")
print(f"=== TRINO ===")
print(f"  MAX(dt): {df.iloc[0]['max_dt']}")
print(f"  Total linhas: {df.iloc[0]['total']}")
client.close()

# Verificar no BigQuery
bq_client = bigquery.Client(project="conect-python-g-sheets")
bq_result = bq_client.query("SELECT MAX(dt) as max_dt, COUNT(*) as total FROM conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air").to_dataframe()
print(f"\n=== BIGQUERY ===")
print(f"  MAX(dt): {bq_result.iloc[0]['max_dt']}")
print(f"  Total linhas: {bq_result.iloc[0]['total']}")

# Comparar
trino_dt = str(df.iloc[0]['max_dt'])
bq_dt = str(bq_result.iloc[0]['max_dt'])
if trino_dt == bq_dt:
    print(f"\n✅ Snapshots sincronizados ({trino_dt})")
else:
    print(f"\n⚠️ Snapshots DIFERENTES! Trino={trino_dt}, BQ={bq_dt}")
    print("   Rode 'python pipeline_local.py' pra sincronizar.")
