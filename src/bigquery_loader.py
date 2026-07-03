"""
Loader de dados do GCS para BigQuery e executor de transformações SQL.

Responsável por carregar dados CSV do GCS em tabelas BigQuery (modo full
e incremental) e executar queries SQL para criação de tabelas derivadas.
Todas as mensagens de log são em português.
"""

import logging
import re
from datetime import date

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class BigQueryLoader:
    """Carrega dados do GCS no BigQuery e executa transformações SQL.

    Responsável por:
    - Carga completa (full): cria tabela se não existe e substitui conteúdo
      com WRITE_TRUNCATE.
    - Carga incremental: substitui o snapshot atual da tabela com WRITE_TRUNCATE.
    - Execução de tabelas derivadas via SQL com WRITE_TRUNCATE.
    - Tratamento de falhas por tabela: registra erro e não lança exceção,
      permitindo que o orchestrator continue com as próximas tabelas.

    Attributes:
        project: ID do projeto GCP.
    """

    def __init__(self, project: str = "conect-python-g-sheets"):
        """Inicializa cliente BigQuery.

        Args:
            project: ID do projeto GCP. Padrão: 'conect-python-g-sheets'.
        """
        self.project = project
        self._client = bigquery.Client(project=self.project)

    def load_full(self, gcs_uri: str, table_id: str) -> None:
        """Carga completa: cria tabela se não existe e substitui todo o conteúdo.

        Utiliza WRITE_TRUNCATE para substituir integralmente o conteúdo da
        tabela de destino. O schema é auto-detectado a partir do CSV.

        Args:
            gcs_uri: URI do arquivo no GCS (ex: gs://bucket/path.csv).
            table_id: ID completo da tabela BigQuery de destino
                (ex: projeto.dataset.tabela).

        Raises:
            Não lança exceção. Registra erro via logging em caso de falha.
        """
        try:
            logger.info(
                "[CARGA_BQ] [INICIO] Tabela: %s | Modo: FULL | "
                "Origem: %s",
                table_id,
                gcs_uri,
            )

            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.CSV,
                autodetect=True,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                skip_leading_rows=1,
            )

            load_job = self._client.load_table_from_uri(
                gcs_uri,
                table_id,
                job_config=job_config,
            )

            load_job.result()  # Aguarda conclusão

            table = self._client.get_table(table_id)
            logger.info(
                "[CARGA_BQ] [SUCESSO] Tabela: %s | Registros: %d | "
                "Carga completa concluída",
                table_id,
                table.num_rows,
            )

        except Exception as e:
            logger.error(
                "[CARGA_BQ] [FALHA] Tabela: %s | Modo: FULL | "
                "Erro: %s",
                table_id,
                str(e),
            )

    def load_partition(
        self, gcs_uri: str, table_id: str, partition_date: date
    ) -> None:
        """Carga idempotente em partição específica da tabela (WRITE_TRUNCATE da partição).

        Substitui apenas os dados da partição dt=partition_date, preservando todas
        as demais partições. Resolve o problema de zeros no Tableau causado pelo
        WRITE_TRUNCATE total (que apagava todas as partições quando o Trino ainda
        não tinha dados do dia).

        Requer que a tabela destino seja date-partitioned pela coluna 'dt'.

        Schema do gold (re_gold_receita_unificado_air):
            advertiser_id STRING, mes_base DATE, tamanho STRING, pacote STRING,
            estado STRING, municipio STRING, ultimo_mes_pagamento DATE,
            status_ts STRING, faturado_mes FLOAT64, classificacao STRING,
            classificacao_rec STRING, classificacao_churn STRING, vigencia_bt STRING,
            dt_cancelado DATE, delta FLOAT64, day_base DATE, day_churn DATE,
            faturado_mes_campanha FLOAT64, status_ts_campanha STRING,
            pago_mes_campanha FLOAT64, faturado_mes_bairro_vip FLOAT64,
            status_ts_bairro_vip STRING, pago_mes_bairro FLOAT64,
            faturado_mes_topo_fixo FLOAT64, status_ts_topo_fixo STRING,
            pago_mes_topo FLOAT64, total_faturado_sva FLOAT64,
            total_pago_sva FLOAT64, canal_conta STRING, dono_conta STRING,
            dt DATE, cordenador STRING, advertiser_industry STRING

        Args:
            gcs_uri: URI do arquivo CSV no GCS (ex: gs://bucket/path/table_2026-07-03.csv).
            table_id: ID completo da tabela BigQuery de destino
                (ex: projeto.dataset.tabela). NÃO incluir o sufixo $YYYYMMDD.
            partition_date: Data da partição a substituir. Apenas os dados
                desta data serão substituídos.

        Raises:
            Não lança exceção. Registra erro via logging em caso de falha.
        """
        try:
            partition_suffix = partition_date.strftime("%Y%m%d")
            table_partition_id = f"{table_id}${partition_suffix}"

            logger.info(
                "[CARGA_BQ] [INICIO] Tabela: %s | Modo: PARTITION | "
                "Partição: %s | Origem: %s",
                table_id,
                partition_date.isoformat(),
                gcs_uri,
            )

            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.CSV,
                autodetect=True,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                skip_leading_rows=1,
                time_partitioning=bigquery.TimePartitioning(
                    type_=bigquery.TimePartitioningType.DAY,
                    field="dt",
                ),
            )

            load_job = self._client.load_table_from_uri(
                gcs_uri,
                table_partition_id,
                job_config=job_config,
            )

            load_job.result()

            table = self._client.get_table(table_id)
            logger.info(
                "[CARGA_BQ] [SUCESSO] Tabela: %s | Registros totais: %d | "
                "Partição %s substituída (histórico preservado)",
                table_id,
                table.num_rows,
                partition_date.isoformat(),
            )

        except Exception as e:
            logger.error(
                "[CARGA_BQ] [FALHA] Tabela: %s | Modo: PARTITION | "
                "Partição: %s | Erro: %s",
                table_id,
                partition_date.isoformat() if partition_date else "N/A",
                str(e),
            )

    def load_append(
        self, gcs_uri: str, table_id: str, partition_column: str = "dt"
    ) -> None:
        """Carga incremental histórica: APPEND para preservar dados anteriores.

        Usada por tabelas históricas (ex: silver) onde cada execução diária
        adiciona apenas os dados do dia, sem apagar o histórico acumulado.

        Args:
            gcs_uri: URI do arquivo no GCS (ex: gs://bucket/table/table_2024-01-15.csv).
            table_id: ID completo da tabela BigQuery de destino.
            partition_column: Nome da coluna de partição. Padrão: 'dt'.

        Raises:
            Não lança exceção. Registra erro via logging em caso de falha.
        """
        try:
            logger.info(
                "[CARGA_BQ] [INICIO] Tabela: %s | Modo: APPEND | "
                "Origem: %s | Coluna partição: %s",
                table_id,
                gcs_uri,
                partition_column,
            )

            partition_date = self._extract_date_from_uri(gcs_uri)

            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.CSV,
                autodetect=True,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                skip_leading_rows=1,
            )

            load_job = self._client.load_table_from_uri(
                gcs_uri,
                table_id,
                job_config=job_config,
            )

            load_job.result()

            table = self._client.get_table(table_id)
            logger.info(
                "[CARGA_BQ] [SUCESSO] Tabela: %s | Registros: %d | "
                "Carga append concluída (dt='%s')",
                table_id,
                table.num_rows,
                partition_date,
            )

        except Exception as e:
            logger.error(
                "[CARGA_BQ] [FALHA] Tabela: %s | Modo: APPEND | "
                "Erro: %s",
                table_id,
                str(e),
            )

    def load_incremental(
        self, gcs_uri: str, table_id: str, partition_column: str = "dt"
    ) -> None:
        """Carga incremental: substitui o snapshot da tabela com WRITE_TRUNCATE.

        Estratégia:
        1. Extrai a data do nome do arquivo no gcs_uri (padrão: tabela_YYYY-MM-DD.csv)
        2. Substitui a tabela destino inteira com o CSV carregado

        Args:
            gcs_uri: URI do arquivo no GCS (ex: gs://bucket/table/table_2024-01-15.csv).
            table_id: ID completo da tabela BigQuery de destino.
            partition_column: Nome da coluna de partição para deduplicação.
                Padrão: 'dt'.

        Raises:
            Não lança exceção. Registra erro via logging em caso de falha.
        """
        try:
            logger.info(
                "[CARGA_BQ] [INICIO] Tabela: %s | Modo: INCREMENTAL | "
                "Origem: %s | Coluna partição: %s",
                table_id,
                gcs_uri,
                partition_column,
            )

            # Extrair data do nome do arquivo (padrão: tabela_YYYY-MM-DD.csv)
            partition_date = self._extract_date_from_uri(gcs_uri)

            if partition_date is None:
                logger.error(
                    "[CARGA_BQ] [FALHA] Tabela: %s | Não foi possível "
                    "extrair data do URI: %s",
                    table_id,
                    gcs_uri,
                )
                return

            # Carga de snapshot: substitui o conteúdo inteiro para evitar
            # divergência de schema entre execuções.
            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.CSV,
                autodetect=True,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                skip_leading_rows=1,
            )

            load_job = self._client.load_table_from_uri(
                gcs_uri,
                table_id,
                job_config=job_config,
            )

            load_job.result()  # Aguarda conclusão do LOAD

            table = self._client.get_table(table_id)
            logger.info(
                "[CARGA_BQ] [SUCESSO] Tabela: %s | Registros: %d | "
                "Carga incremental concluída (snapshot dt='%s')",
                table_id,
                table.num_rows,
                partition_date,
            )

        except Exception as e:
            logger.error(
                "[CARGA_BQ] [FALHA] Tabela: %s | Modo: INCREMENTAL | "
                "Erro: %s",
                table_id,
                str(e),
            )

    def execute_derived_table(self, query: str, destination_table: str) -> None:
        """Executa SQL de transformação e grava resultado com WRITE_TRUNCATE.

        Executa uma query SQL de transformação e grava o resultado na tabela
        de destino, substituindo integralmente o conteúdo anterior.

        Args:
            query: Query SQL de transformação a ser executada.
            destination_table: ID completo da tabela BigQuery de destino
                (ex: projeto.dataset.tabela_derivada).

        Raises:
            Não lança exceção. Registra erro via logging em caso de falha.
        """
        try:
            logger.info(
                "[TABELA_DERIVADA] [INICIO] Tabela destino: %s | "
                "Executando transformação SQL",
                destination_table,
            )

            job_config = bigquery.QueryJobConfig(
                destination=destination_table,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            )

            query_job = self._client.query(query, job_config=job_config)
            query_job.result()  # Aguarda conclusão

            table = self._client.get_table(destination_table)
            logger.info(
                "[TABELA_DERIVADA] [SUCESSO] Tabela destino: %s | "
                "Registros: %d | Transformação concluída",
                destination_table,
                table.num_rows,
            )

        except Exception as e:
            logger.error(
                "[TABELA_DERIVADA] [FALHA] Tabela destino: %s | "
                "Erro: %s",
                destination_table,
                str(e),
            )

    def _extract_date_from_uri(self, gcs_uri: str) -> str | None:
        """Extrai a data do nome do arquivo no URI do GCS.

        Espera o padrão: gs://bucket/table_name/table_name_YYYY-MM-DD.csv

        Args:
            gcs_uri: URI completo do arquivo no GCS.

        Returns:
            String da data no formato 'YYYY-MM-DD' ou None se não encontrada.
        """
        match = re.search(r"(\d{4}-\d{2}-\d{2})\.csv$", gcs_uri)
        if match:
            return match.group(1)
        return None
