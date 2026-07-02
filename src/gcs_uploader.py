"""
Uploader de arquivos CSV para Google Cloud Storage.

Responsável por fazer upload de arquivos extraídos para o bucket GCS
do projeto, com retry automático e remoção do arquivo local após sucesso.
Todas as mensagens de log são em português.
"""

import logging
import os
import time
from datetime import date

from google.cloud import storage

logger = logging.getLogger(__name__)


class GCSUploader:
    """Faz upload de arquivos CSV para bucket GCS com retry.

    Responsável por:
    - Inicializar cliente GCS com Application Default Credentials (ADC)
    - Construir o caminho (path) do arquivo no GCS seguindo o padrão definido
    - Realizar upload com sobrescrita e retry automático (3 tentativas, 30s intervalo)
    - Remover o arquivo local após upload com sucesso
    - Manter o arquivo local caso o upload falhe após todas as tentativas

    Attributes:
        project: ID do projeto GCP.
        bucket_name: Nome do bucket GCS de destino.
    """

    RETRY_ATTEMPTS = 3
    RETRY_INTERVAL_SECONDS = 30

    def __init__(self, project: str = "conect-python-g-sheets", bucket_name: str = "teste-extracao-trino"):
        """Inicializa cliente GCS com ADC (Application Default Credentials).

        Args:
            project: ID do projeto GCP. Padrão: 'conect-python-g-sheets'.
            bucket_name: Nome do bucket GCS de destino.
                Padrão: 'teste-extracao-trino'.
        """
        self.project = project
        self.bucket_name = bucket_name
        self._client = storage.Client(project=self.project)
        self._bucket = self._client.bucket(self.bucket_name)

    def build_gcs_path(self, table_name: str, extraction_date: date | None = None) -> str:
        """Gera o caminho do arquivo no GCS.

        O padrão de nomenclatura é:
            {table_name}/{table_name}_{YYYY-MM-DD}.csv

        Args:
            table_name: Nome curto da tabela (sem prefixo catálogo/schema).
            extraction_date: Data de extração. Se None, usa a data atual.

        Returns:
            Caminho completo do arquivo no GCS.
        """
        if extraction_date is None:
            extraction_date = date.today()

        date_str = extraction_date.strftime("%Y-%m-%d")
        return f"{table_name}/{table_name}_{date_str}.csv"

    def upload(self, local_path: str, gcs_path: str) -> None:
        """Faz upload de arquivo local para o GCS com sobrescrita.

        Realiza até 3 tentativas com intervalo de 30 segundos entre elas.
        - Se o upload for bem-sucedido, remove o arquivo local.
        - Se o upload falhar após todas as tentativas, mantém o arquivo
          local para retry manual.

        Args:
            local_path: Caminho do arquivo local a ser enviado.
            gcs_path: Caminho de destino no bucket GCS.

        Raises:
            Não lança exceção. Registra erro via logging e mantém
            o arquivo local em caso de falha.
        """
        last_exception: Exception | None = None

        for attempt in range(1, self.RETRY_ATTEMPTS + 1):
            try:
                logger.info(
                    "[UPLOAD_GCS] [TENTATIVA %d/%d] Tabela: %s | "
                    "Enviando arquivo '%s' para 'gs://%s/%s'",
                    attempt,
                    self.RETRY_ATTEMPTS,
                    gcs_path.split("/")[0] if "/" in gcs_path else gcs_path,
                    local_path,
                    self.bucket_name,
                    gcs_path,
                )

                blob = self._bucket.blob(gcs_path)
                blob.upload_from_filename(local_path)

                logger.info(
                    "[UPLOAD_GCS] [SUCESSO] Tabela: %s | "
                    "Arquivo enviado com sucesso para 'gs://%s/%s'",
                    gcs_path.split("/")[0] if "/" in gcs_path else gcs_path,
                    self.bucket_name,
                    gcs_path,
                )

                # Upload bem-sucedido: remover arquivo local
                try:
                    os.remove(local_path)
                    logger.info(
                        "[UPLOAD_GCS] [LIMPEZA] Arquivo local removido: '%s'",
                        local_path,
                    )
                except OSError as e:
                    logger.warning(
                        "[UPLOAD_GCS] [AVISO] Não foi possível remover "
                        "arquivo local '%s': %s",
                        local_path,
                        e,
                    )

                return

            except Exception as e:
                last_exception = e
                logger.warning(
                    "[UPLOAD_GCS] [FALHA] Tabela: %s | Tentativa %d/%d "
                    "falhou: %s",
                    gcs_path.split("/")[0] if "/" in gcs_path else gcs_path,
                    attempt,
                    self.RETRY_ATTEMPTS,
                    str(e),
                )

                if attempt < self.RETRY_ATTEMPTS:
                    logger.info(
                        "[UPLOAD_GCS] [AGUARDANDO] Próxima tentativa em %d segundos...",
                        self.RETRY_INTERVAL_SECONDS,
                    )
                    time.sleep(self.RETRY_INTERVAL_SECONDS)

        # Todas as tentativas falharam: manter arquivo local
        logger.error(
            "[UPLOAD_GCS] [FALHA] Tabela: %s | Upload falhou após %d "
            "tentativas. Último erro: %s. Arquivo local mantido em '%s' "
            "para retry manual.",
            gcs_path.split("/")[0] if "/" in gcs_path else gcs_path,
            self.RETRY_ATTEMPTS,
            str(last_exception),
            local_path,
        )
