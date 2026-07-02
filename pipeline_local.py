"""
Pipeline Local — Trino → Parquet (chunks) → GCS → BigQuery
Executa com VPN conectada: python pipeline_local.py
"""

import os
import sys
import time
import logging
from datetime import datetime, date, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from trino.dbapi import connect
from trino.auth import BasicAuthentication
from google.cloud import storage, bigquery
from dotenv import load_dotenv

# ============================================================
# Configuração
# ============================================================

load_dotenv("credenciais.env")
load_dotenv("projeto_meu/credenciais.env")

PROJECT_ID = "conect-python-g-sheets"
BUCKET_NAME = "teste-extracao-trino"
DATASET = "planejamento_comercial"

TRINO_HOST = "trino-gateway.dataeng.bigdata.olxbr.io"
TRINO_PORT = 443
TRINO_USER = os.getenv("AD_USER_NAME", "")
TRINO_PASS = os.getenv("AD_USER_PASSWORD", "")

TABELAS = [
    {
        "full_name": "hive.planejamento.re_gold_receita_unificado_air",
        "short_name": "re_gold_receita_unificado_air",
        "partition_column": "dt",
        "use_yesterday": False,
        "use_max_dt": False,
        "tipo": "standard",
        "sql_file": None,
    },
    {
        "full_name": "hive.planejamento.re_silver_receita_cb_air",
        "short_name": "re_silver_receita_cb_air",
        "partition_column": "dt",
        "use_yesterday": False,
        "use_max_dt": False,
        "tipo": "standard",
        "sql_file": None,
    },
    {
        "full_name": "hive.planejamento.re_silver_planos_periodicos_cb",
        "short_name": "re_silver_planos_periodicos_cb",
        "partition_column": "dt",
        "use_yesterday": False,
        "use_max_dt": True,
        "tipo": "standard",
        "sql_file": None,
    },
    {
        "full_name": "hive.planejamento.re_silver_receita_cb_paids_air",
        "short_name": "re_silver_receita_cb_paids_air",
        "partition_column": "dt",
        "use_yesterday": False,
        "use_max_dt": False,
        "tipo": "standard",
        "sql_file": None,
    },
    {
        "full_name": None,
        "short_name": "desconto_faseado",
        "partition_column": None,
        "use_yesterday": False,
        "use_max_dt": False,
        "tipo": "custom",
        "sql_file": "sql/desconto_faseado.sql",
    },
    {
        "full_name": None,
        "short_name": "radar_cohort",
        "partition_column": None,
        "use_yesterday": False,
        "use_max_dt": False,
        "tipo": "custom",
        "sql_file": "sql/radar_cohort.sql",
    },
]

CHUNK_SIZE = 100_000
TMP_DIR = Path("tmp_parquet")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ============================================================
# Funções
# ============================================================


def conectar_trino():
    if not TRINO_USER or not TRINO_PASS:
        logger.error("Variáveis AD_USER_NAME ou AD_USER_PASSWORD não definidas!")
        sys.exit(1)

    logger.info(f"Conectando ao Trino: {TRINO_HOST}:{TRINO_PORT}")
    conn = connect(
        host=TRINO_HOST,
        port=TRINO_PORT,
        http_scheme="https",
        auth=BasicAuthentication(TRINO_USER, TRINO_PASS),
        user=TRINO_USER,
        source="dataeng-trino-api",
    )
    cursor = conn.cursor()
    cursor.execute("SELECT 1")
    cursor.fetchone()
    cursor.close()
    logger.info("Conexão com Trino OK!")
    return conn


def extrair_tabela(conn, tabela: dict) -> Path:
    short_name = tabela["short_name"]

    if tabela.get("tipo") == "custom":
        # Query customizada lida de arquivo SQL
        sql_path = Path(tabela["sql_file"])
        if not sql_path.exists():
            raise FileNotFoundError(f"SQL não encontrado: {sql_path}")
        query = sql_path.read_text(encoding="utf-8")
        logger.info(f"Extraindo (custom): {short_name} via {sql_path}")
    else:
        # Extração padrão: SELECT * com filtro de partição
        full_name = tabela["full_name"]
        partition_col = tabela["partition_column"]

        if tabela.get("use_max_dt", False):
            logger.info(f"Buscando MAX({partition_col}) de {full_name}...")
            cursor = conn.cursor()
            cursor.execute(f"SELECT MAX({partition_col}) FROM {full_name}")
            row = cursor.fetchone()
            cursor.close()
            if row and row[0]:
                data_filtro = str(row[0])
                logger.info(f"  MAX(dt) encontrado: {data_filtro}")
            else:
                raise ValueError(f"Tabela {short_name}: MAX(dt) retornou NULL")
        elif tabela.get("use_yesterday", False):
            data_filtro = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        else:
            data_filtro = date.today().strftime("%Y-%m-%d")

        query = f"SELECT * FROM {full_name} WHERE {partition_col} = CAST('{data_filtro}' AS DATE)"
        logger.info(f"Extraindo: {short_name} (dt={data_filtro})")

    TMP_DIR.mkdir(exist_ok=True)
    output_path = TMP_DIR / f"{short_name}.parquet"
    if output_path.exists():
        output_path.unlink()

    all_chunks = []
    total_rows = 0

    for chunk in pd.read_sql(query, conn, chunksize=CHUNK_SIZE):
        all_chunks.append(chunk)
        total_rows += len(chunk)
        logger.info(f"  {short_name}: {total_rows} linhas...")

    if not all_chunks:
        logger.warning(f"  {short_name}: nenhuma linha retornada!")
        raise ValueError(f"Tabela {short_name} retornou 0 linhas")

    df_full = pd.concat(all_chunks, ignore_index=True)
    table = pa.Table.from_pandas(df_full)
    pq.write_table(table, str(output_path), compression="snappy")

    logger.info(f"  OK: {short_name} — {total_rows} linhas em {output_path}")
    return output_path


def upload_para_gcs(local_path: Path, short_name: str) -> str:
    cliente_gcs = storage.Client(PROJECT_ID)
    bucket = cliente_gcs.bucket(BUCKET_NAME)
    gcs_path = f"{short_name}/{short_name}.parquet"
    blob = bucket.blob(gcs_path)

    logger.info(f"  Upload: gs://{BUCKET_NAME}/{gcs_path}")
    blob.upload_from_filename(str(local_path))
    local_path.unlink()

    return f"gs://{BUCKET_NAME}/{gcs_path}"


def carregar_no_bigquery(gcs_uri: str, short_name: str):
    cliente_bq = bigquery.Client(project=PROJECT_ID)
    table_id = f"{PROJECT_ID}.{DATASET}.{short_name}"

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    logger.info(f"  BigQuery: {table_id}")
    load_job = cliente_bq.load_table_from_uri(gcs_uri, table_id, job_config=job_config)
    load_job.result()

    table = cliente_bq.get_table(table_id)
    logger.info(f"  OK: {table.num_rows} linhas carregadas")


# ============================================================
# Main
# ============================================================


DERIVED_TABLES = [
    {"name": "receita_consolidada", "destination": f"{PROJECT_ID}.{DATASET}.receita_consolidada", "sql_file": "sql/receita_consolidada.sql", "order": 1},
    {"name": "cb_pagamentos", "destination": f"{PROJECT_ID}.{DATASET}.cb_pagamentos", "sql_file": "sql/cb_pagamentos.sql", "order": 2},
    {"name": "receita_enriquecida", "destination": f"{PROJECT_ID}.{DATASET}.receita_enriquecida", "sql_file": "sql/receita_enriquecida.sql", "order": 3},
    {"name": "bd_planos_uf", "destination": f"{PROJECT_ID}.{DATASET}.bd_planos_uf", "sql_file": "sql/bd_planos_uf.sql", "order": 4},
    {"name": "bd_planos_mensais_sva", "destination": f"{PROJECT_ID}.{DATASET}.bd_planos_mensais_sva", "sql_file": "sql/bd_planos_mensais_sva.sql", "order": 5},
    {"name": "planos_periodicos", "destination": f"{PROJECT_ID}.{DATASET}.planos_periodicos", "sql_file": "sql/planos_periodicos.sql", "order": 6},
    {"name": "bd_planos_periodicos", "destination": f"{PROJECT_ID}.{DATASET}.bd_planos_periodicos", "sql_file": "sql/bd_planos_periodicos.sql", "order": 7},
    {"name": "bd_full", "destination": f"{PROJECT_ID}.{DATASET}.bd_full", "sql_file": "sql/bd_full.sql", "order": 8},
    {"name": "diarizacao", "destination": f"{PROJECT_ID}.{DATASET}.diarizacao", "sql_file": "sql/diarizacao.sql", "order": 9},
]


def executar_tabelas_derivadas():
    """Executa queries SQL de tabelas derivadas em ordem."""
    cliente_bq = bigquery.Client(project=PROJECT_ID)
    derivadas_ok = []
    derivadas_erro = []

    sorted_tables = sorted(DERIVED_TABLES, key=lambda x: x["order"])

    for dt in sorted_tables:
        sql_path = Path(dt["sql_file"])
        if not sql_path.exists():
            logger.warning(f"  SQL não encontrado: {sql_path} — pulando {dt['name']}")
            continue

        try:
            query = sql_path.read_text(encoding="utf-8")
            logger.info(f"  Executando: {dt['name']} → {dt['destination']}")

            job_config = bigquery.QueryJobConfig(
                destination=dt["destination"],
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            )
            job = cliente_bq.query(query, job_config=job_config)
            job.result()

            table = cliente_bq.get_table(dt["destination"])
            logger.info(f"  OK: {dt['name']} — {table.num_rows} linhas")
            derivadas_ok.append(dt["name"])

        except Exception as e:
            logger.error(f"  ERRO {dt['name']}: {e}")
            derivadas_erro.append(dt["name"])

    return derivadas_ok, derivadas_erro


def main():
    inicio = time.time()
    logger.info("=" * 50)
    logger.info("PIPELINE DE DADOS - PLANEJAMENTO COMERCIAL")
    logger.info("=" * 50)

    tabelas_ok = []
    tabelas_erro = []

    try:
        conn = conectar_trino()
    except Exception as e:
        logger.error(f"FALHA TRINO: {e}")
        logger.error("VPN ligada? Credenciais corretas?")
        sys.exit(1)

    try:
        for tabela in TABELAS:
            short_name = tabela["short_name"]
            parquet_path = None
            try:
                parquet_path = extrair_tabela(conn, tabela)
                gcs_uri = upload_para_gcs(parquet_path, short_name)
                carregar_no_bigquery(gcs_uri, short_name)
                tabelas_ok.append(short_name)
            except Exception as e:
                logger.error(f"ERRO {short_name}: {e}")
                tabelas_erro.append(short_name)
                if parquet_path and parquet_path.exists():
                    parquet_path.unlink()
                    logger.info(f"  Parquet temporário removido: {parquet_path}")
    finally:
        conn.close()

    # Executar tabelas derivadas
    logger.info("-" * 50)
    logger.info("TABELAS DERIVADAS")
    logger.info("-" * 50)
    derivadas_ok, derivadas_erro = executar_tabelas_derivadas()

    duracao = time.time() - inicio
    logger.info("=" * 50)
    logger.info(f"Duração: {duracao:.1f}s")
    logger.info(f"Extração OK: {tabelas_ok}")
    logger.info(f"Extração Erro: {tabelas_erro}")
    logger.info(f"Derivadas OK: {derivadas_ok}")
    logger.info(f"Derivadas Erro: {derivadas_erro}")
    logger.info("=" * 50)

    return 1 if (tabelas_erro or derivadas_erro) else 0


if __name__ == "__main__":
    # Uso: python pipeline_local.py              → pipeline completo
    #      python pipeline_local.py --derivadas  → só tabelas derivadas (sem Trino)
    if "--derivadas" in sys.argv:
        logger.info("=" * 50)
        logger.info("EXECUTANDO APENAS TABELAS DERIVADAS")
        logger.info("=" * 50)
        ok, erro = executar_tabelas_derivadas()
        logger.info(f"OK: {ok}")
        logger.info(f"Erro: {erro}")
        sys.exit(1 if erro else 0)
    else:
        sys.exit(main())
