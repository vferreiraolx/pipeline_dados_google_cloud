"""
Gerenciador de estado de extração do Pipeline de Dados.

Controla se uma tabela já teve a primeira carga (full) ou se deve
realizar extração incremental, persistindo o estado no BigQuery
na tabela `pipeline_metadata.extraction_state`.
"""

import logging
from datetime import datetime

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class StateManager:
    """Controla o estado de extração das tabelas do pipeline.

    Utiliza a tabela BigQuery `pipeline_metadata.extraction_state` para
    persistir o estado de cada tabela extraída, permitindo determinar
    se a próxima execução deve ser full (primeira carga) ou incremental.

    Attributes:
        project: ID do projeto GCP.
        dataset: Nome do dataset de metadados.
    """

    def __init__(
        self,
        project: str = "conect-python-g-sheets",
        dataset: str = "pipeline_metadata",
    ):
        """Inicializa o StateManager com cliente BigQuery.

        Cria a tabela de estado caso ela não exista.

        Args:
            project: ID do projeto GCP. Padrão: 'conect-python-g-sheets'.
            dataset: Nome do dataset para metadados. Padrão: 'pipeline_metadata'.
        """
        self.project = project
        self.dataset = dataset
        self._client = bigquery.Client(project=self.project)
        self._table_id = f"{self.project}.{self.dataset}.extraction_state"
        self._ensure_table_exists()

    def _ensure_table_exists(self) -> None:
        """Cria a tabela de estado e o dataset caso não existam.

        Schema da tabela extraction_state:
        - table_name: STRING (nome curto da tabela)
        - last_extraction_date: DATE (data da última extração)
        - rows_extracted: INT64 (linhas extraídas na última execução)
        - extraction_type: STRING ('full' ou 'incremental')
        - status: STRING ('success' ou 'failed')
        - updated_at: TIMESTAMP (timestamp da atualização)
        """
        try:
            # Garantir que o dataset existe
            dataset_ref = bigquery.DatasetReference(self.project, self.dataset)
            try:
                self._client.get_dataset(dataset_ref)
            except Exception:
                dataset = bigquery.Dataset(dataset_ref)
                dataset.location = "US"
                self._client.create_dataset(dataset, exists_ok=True)
                logger.info(
                    "[ESTADO] [SUCESSO] Dataset '%s' criado com sucesso",
                    self.dataset,
                )

            # Criar tabela se não existir
            schema = [
                bigquery.SchemaField("table_name", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("last_extraction_date", "DATE", mode="REQUIRED"),
                bigquery.SchemaField("rows_extracted", "INT64", mode="REQUIRED"),
                bigquery.SchemaField("extraction_type", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
            ]

            table = bigquery.Table(self._table_id, schema=schema)
            self._client.create_table(table, exists_ok=True)
            logger.info(
                "[ESTADO] [SUCESSO] Tabela de estado '%s' verificada/criada",
                self._table_id,
            )

        except Exception as e:
            logger.error(
                "[ESTADO] [FALHA] Erro ao criar tabela de estado: %s",
                str(e),
            )
            raise

    def is_first_load(self, table_name: str) -> bool:
        """Verifica se a tabela já foi extraída anteriormente com sucesso.

        Consulta a tabela extraction_state buscando registros com
        status='success' para a tabela informada.

        Args:
            table_name: Nome curto da tabela a verificar.

        Returns:
            True se não existe extração anterior bem-sucedida (primeira carga),
            False se já existe pelo menos uma extração com sucesso.
        """
        try:
            query = (
                f"SELECT COUNT(*) as total "
                f"FROM `{self._table_id}` "
                f"WHERE table_name = @table_name AND status = 'success'"
            )

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter(
                        "table_name", "STRING", table_name
                    )
                ]
            )

            query_job = self._client.query(query, job_config=job_config)
            results = query_job.result()

            for row in results:
                is_first = row.total == 0
                if is_first:
                    logger.info(
                        "[ESTADO] [INICIO] Tabela: %s | "
                        "Primeira carga detectada (nenhuma extração anterior)",
                        table_name,
                    )
                else:
                    logger.info(
                        "[ESTADO] [INICIO] Tabela: %s | "
                        "Extração anterior encontrada — modo incremental",
                        table_name,
                    )
                return is_first

            # Se não retornou nenhuma linha, considerar como primeira carga
            return True

        except Exception as e:
            logger.error(
                "[ESTADO] [FALHA] Tabela: %s | "
                "Erro ao verificar estado: %s — assumindo primeira carga",
                table_name,
                str(e),
            )
            return True

    def mark_loaded(
        self,
        table_name: str,
        load_date: str,
        rows_count: int,
        extraction_type: str = "incremental",
        status: str = "success",
    ) -> None:
        """Registra uma extração na tabela de estado.

        Insere um novo registro na tabela extraction_state com os dados
        da extração realizada. Cada execução gera um novo registro;
        o registro mais recente determina o estado atual da tabela.

        Args:
            table_name: Nome curto da tabela extraída.
            load_date: Data da extração no formato 'YYYY-MM-DD'.
            rows_count: Quantidade de linhas extraídas.
            extraction_type: Tipo de extração ('full' ou 'incremental').
                Padrão: 'incremental'.
            status: Status da extração ('success' ou 'failed').
                Padrão: 'success'.
        """
        try:
            now = datetime.now().isoformat()

            rows_to_insert = [
                {
                    "table_name": table_name,
                    "last_extraction_date": load_date,
                    "rows_extracted": rows_count,
                    "extraction_type": extraction_type,
                    "status": status,
                    "updated_at": now,
                }
            ]

            errors = self._client.insert_rows_json(
                self._table_id, rows_to_insert
            )

            if errors:
                logger.error(
                    "[ESTADO] [FALHA] Tabela: %s | "
                    "Erro ao registrar extração: %s",
                    table_name,
                    str(errors),
                )
            else:
                logger.info(
                    "[ESTADO] [SUCESSO] Tabela: %s | Data: %s | "
                    "Registros: %d | Tipo: %s | Status: %s | "
                    "Estado de extração registrado",
                    table_name,
                    load_date,
                    rows_count,
                    extraction_type,
                    status,
                )

        except Exception as e:
            logger.error(
                "[ESTADO] [FALHA] Tabela: %s | "
                "Erro ao registrar extração: %s",
                table_name,
                str(e),
            )
