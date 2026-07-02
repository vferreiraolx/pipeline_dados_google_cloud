"""
Módulo de extração de dados do Trino.

Gerencia conexão com o Trino Gateway via HTTPS e extrai dados
de tabelas Hive em lotes, salvando os resultados em arquivos CSV.
"""

import csv
import logging
import os
import time
from datetime import date

from trino.auth import BasicAuthentication
from trino.dbapi import connect as trino_connect

from src.exceptions import CredentialError

logger = logging.getLogger(__name__)


class TrinoExtractor:
    """Conecta ao Trino e extrai dados em lotes.

    Attributes:
        host: Endereço do Trino Gateway.
        port: Porta de conexão (443 para HTTPS).
        username: Usuário AD para autenticação.
        password: Senha AD para autenticação.
        source: Identificador da fonte de dados.
        timeout: Timeout de conexão em segundos.
        retry_attempts: Número de tentativas de conexão.
        retry_interval: Intervalo em segundos entre tentativas.
        _connection: Objeto de conexão com o Trino.
    """

    def __init__(self):
        """Inicializa o TrinoExtractor com credenciais AD de variáveis de ambiente.

        Lê TRINO_USER e TRINO_PASSWORD das variáveis de ambiente.

        Raises:
            CredentialError: Se as variáveis de ambiente estiverem ausentes ou vazias.
        """
        self.host = "trino-gateway.dataeng.bigdata.olxbr.io"
        self.port = 443
        self.source = "dataeng-trino-api"
        self.timeout = 30
        self.retry_attempts = 3
        self.retry_interval = 5

        missing_vars = []
        self.username = os.environ.get("TRINO_USER", "").strip()
        self.password = os.environ.get("TRINO_PASSWORD", "").strip()

        if not self.username:
            missing_vars.append("TRINO_USER")
        if not self.password:
            missing_vars.append("TRINO_PASSWORD")

        if missing_vars:
            raise CredentialError(
                f"Variáveis de ambiente obrigatórias ausentes ou vazias: "
                f"{', '.join(missing_vars)}"
            )

        self._connection = None

    def connect(self):
        """Estabelece conexão HTTPS com o Trino Gateway.

        Realiza até 3 tentativas com intervalo de 5 segundos entre elas.
        Em cada tentativa, tenta criar a conexão e executar um comando
        simples para verificar que a conexão está funcional.

        Raises:
            ConnectionError: Se todas as tentativas de conexão falharem.
        """
        last_exception = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                logger.info(
                    f"Tentativa {attempt}/{self.retry_attempts} de conexão com Trino "
                    f"em {self.host}:{self.port}"
                )
                self._connection = trino_connect(
                    host=self.host,
                    port=self.port,
                    user=self.username,
                    auth=BasicAuthentication(self.username, self.password),
                    http_scheme="https",
                    source=self.source,
                    request_timeout=self.timeout,
                )
                # Verify connection is working
                cursor = self._connection.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.close()

                logger.info("Conexão com Trino estabelecida com sucesso.")
                return

            except Exception as e:
                last_exception = e
                logger.warning(
                    f"Tentativa {attempt}/{self.retry_attempts} falhou: {str(e)}"
                )
                if attempt < self.retry_attempts:
                    time.sleep(self.retry_interval)

        error_msg = (
            f"Falha ao conectar com Trino após {self.retry_attempts} tentativas. "
            f"Último erro: {str(last_exception)}"
        )
        logger.error(error_msg)
        raise ConnectionError(error_msg)

    def extract_full(
        self, table: str, output_path: str, batch_size: int = 100_000
    ) -> int:
        """Realiza extração completa de todos os registros da tabela.

        Extrai dados em lotes de batch_size linhas e salva em arquivo CSV.

        Args:
            table: Nome completo da tabela no Trino (ex: hive.planejamento.tabela).
            output_path: Caminho do arquivo CSV de saída.
            batch_size: Número de linhas por lote (padrão: 100.000).

        Returns:
            Total de linhas extraídas.

        Raises:
            RuntimeError: Se a conexão não estiver estabelecida.
            Exception: Se ocorrer erro durante a extração.
        """
        if self._connection is None:
            raise RuntimeError(
                "Conexão com Trino não estabelecida. Execute connect() primeiro."
            )

        query = f"SELECT * FROM {table}"
        logger.info(f"Iniciando extração completa da tabela: {table}")

        return self._execute_extraction(query, output_path, batch_size, table)

    def extract_custom(
        self, query: str, output_path: str, batch_size: int = 100_000
    ) -> int:
        """Realiza extração usando SQL customizado.

        Args:
            query: Query SQL completa a ser executada.
            output_path: Caminho do arquivo CSV de saída.
            batch_size: Número de linhas por lote (padrão: 100.000).

        Returns:
            Total de linhas extraídas.

        Raises:
            RuntimeError: Se a conexão não estiver estabelecida.
        """
        if self._connection is None:
            raise RuntimeError(
                "Conexão com Trino não estabelecida. Execute connect() primeiro."
            )

        logger.info("Iniciando extração com SQL customizado")
        return self._execute_extraction(query, output_path, batch_size, "custom_sql")

    def extract_incremental(
        self,
        table: str,
        partition_column: str,
        output_path: str,
        batch_size: int = 100_000,
    ) -> int:
        """Realiza extração incremental filtrando pela partição dt do dia atual.

        Extrai dados em lotes de batch_size linhas e salva em arquivo CSV.

        Args:
            table: Nome completo da tabela no Trino (ex: hive.planejamento.tabela).
            partition_column: Nome da coluna de partição (ex: 'dt').
            output_path: Caminho do arquivo CSV de saída.
            batch_size: Número de linhas por lote (padrão: 100.000).

        Returns:
            Total de linhas extraídas.

        Raises:
            RuntimeError: Se a conexão não estiver estabelecida.
            Exception: Se ocorrer erro durante a extração.
        """
        if self._connection is None:
            raise RuntimeError(
                "Conexão com Trino não estabelecida. Execute connect() primeiro."
            )

        data_atual = date.today().strftime("%Y-%m-%d")
        query = f"SELECT * FROM {table} WHERE {partition_column} = DATE '{data_atual}'"
        logger.info(
            f"Iniciando extração incremental da tabela: {table} "
            f"(filtro: {partition_column} = '{data_atual}')"
        )

        return self._execute_extraction(query, output_path, batch_size, table)

    def _execute_extraction(
        self, query: str, output_path: str, batch_size: int, table: str
    ) -> int:
        """Executa a query e salva resultados em CSV em lotes.

        Args:
            query: Query SQL a ser executada.
            output_path: Caminho do arquivo CSV de saída.
            batch_size: Número de linhas por lote.
            table: Nome da tabela (para logging).

        Returns:
            Total de linhas extraídas.
        """
        total_rows = 0
        cursor = self._connection.cursor()

        try:
            cursor.execute(query)
            columns = [desc[0] for desc in cursor.description]

            with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(columns)

                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    writer.writerows(rows)
                    total_rows += len(rows)
                    logger.info(
                        f"Tabela {table}: {total_rows} linhas extraídas até agora..."
                    )

            logger.info(
                f"Extração da tabela {table} concluída. Total: {total_rows} linhas."
            )
            return total_rows

        finally:
            cursor.close()

    def close(self):
        """Fecha a conexão com o Trino.

        Fecha a conexão independentemente de sucesso ou falha nas operações
        anteriores. Seguro para chamar múltiplas vezes.
        """
        if self._connection is not None:
            try:
                self._connection.close()
                logger.info("Conexão com Trino fechada com sucesso.")
            except Exception as e:
                logger.warning(f"Erro ao fechar conexão com Trino: {str(e)}")
            finally:
                self._connection = None
