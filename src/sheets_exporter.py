"""
Exportador de dados do BigQuery para Google Sheets.

Responsável por ler dados de tabelas BigQuery e exportá-los para
abas de planilhas Google Sheets, substituindo integralmente o conteúdo
anterior. Implementa retry com backoff exponencial para erros transitórios.
Todas as mensagens de log são em português.
"""

import logging
import time
from datetime import datetime

import gspread
from google.cloud import bigquery
from google.oauth2.service_account import Credentials
from requests.exceptions import ConnectionError as RequestsConnectionError

logger = logging.getLogger(__name__)

# Escopos necessários para Google Sheets API
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class SheetsExporter:
    """Exporta dados do BigQuery para Google Sheets.

    Responsável por:
    - Autenticar via service account com gspread.
    - Ler dados de tabelas BigQuery (cabeçalhos + linhas).
    - Substituir integralmente o conteúdo de uma aba de destino.
    - Retry com backoff exponencial (2s, 4s, 8s) para erros
      transitórios e throttling da API.
    - Continuar com demais exportações se uma falhar definitivamente.
    - Registrar log de erro detalhado com nome da tabela, ID da planilha,
      timestamp e descrição do erro.

    Attributes:
        _gc: Cliente gspread autenticado.
        _bq_client: Cliente BigQuery para leitura de dados.
    """

    # Configuração de retry
    MAX_RETRIES = 3
    BASE_BACKOFF_SECONDS = 2  # 2s, 4s, 8s

    def __init__(self):
        """Inicializa com credenciais de service account via gspread.

        Utiliza Application Default Credentials (ADC) para autenticação
        tanto no Google Sheets quanto no BigQuery.
        """
        credentials = Credentials.from_service_account_file(
            "credentials.json", scopes=SCOPES
        )
        self._gc = gspread.authorize(credentials)
        self._bq_client = bigquery.Client()

    def export(self, table_id: str, spreadsheet_id: str, sheet_name: str) -> None:
        """Exporta dados de uma tabela BigQuery para uma aba do Google Sheets.

        Lê todos os dados da tabela BigQuery especificada (cabeçalhos + linhas),
        abre a planilha de destino, seleciona a aba pelo nome, limpa todo o
        conteúdo existente e escreve os novos dados, substituindo integralmente
        o conteúdo anterior.

        Implementa retry com backoff exponencial (2s, 4s, 8s) para erros
        transitórios da API do Google Sheets (APIError, ConnectionError).
        Se todas as tentativas falharem, registra log de erro e não lança
        exceção, permitindo que o orchestrator continue com as demais
        exportações.

        Args:
            table_id: ID completo da tabela BigQuery de origem
                (ex: projeto.dataset.tabela).
            spreadsheet_id: ID da planilha Google Sheets de destino.
            sheet_name: Nome da aba de destino dentro da planilha.
        """
        logger.info(
            "[EXPORTAÇÃO_SHEETS] [INICIO] Tabela: %s | "
            "Planilha: %s | Aba: %s",
            table_id,
            spreadsheet_id,
            sheet_name,
        )

        # Ler dados do BigQuery
        try:
            data = self._read_bigquery_data(table_id)
        except Exception as e:
            self._log_export_error(table_id, spreadsheet_id, sheet_name, e)
            return

        if not data:
            logger.warning(
                "[EXPORTAÇÃO_SHEETS] [AVISO] Tabela: %s | "
                "Nenhum dado encontrado para exportação",
                table_id,
            )
            return

        # Exportar para Google Sheets com retry
        last_exception = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                self._write_to_sheet(spreadsheet_id, sheet_name, data)
                logger.info(
                    "[EXPORTAÇÃO_SHEETS] [SUCESSO] Tabela: %s | "
                    "Planilha: %s | Aba: %s | Registros: %d",
                    table_id,
                    spreadsheet_id,
                    sheet_name,
                    len(data) - 1,  # Exclui cabeçalho da contagem
                )
                return
            except (gspread.exceptions.APIError, RequestsConnectionError) as e:
                last_exception = e
                if attempt < self.MAX_RETRIES:
                    backoff = self.BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "[EXPORTAÇÃO_SHEETS] [RETRY] Tabela: %s | "
                        "Tentativa %d/%d falhou | "
                        "Aguardando %ds antes de nova tentativa | Erro: %s",
                        table_id,
                        attempt,
                        self.MAX_RETRIES,
                        backoff,
                        str(e),
                    )
                    time.sleep(backoff)
                else:
                    # Todas as tentativas esgotadas
                    self._log_export_error(
                        table_id, spreadsheet_id, sheet_name, e
                    )
            except Exception as e:
                # Erro não transitório — falha definitiva sem retry
                self._log_export_error(table_id, spreadsheet_id, sheet_name, e)
                return

    def _read_bigquery_data(self, table_id: str) -> list[list]:
        """Lê todos os dados de uma tabela BigQuery.

        Executa SELECT * na tabela e retorna uma lista de listas,
        onde a primeira lista contém os nomes das colunas (cabeçalhos)
        e as demais contêm os valores de cada linha.

        Args:
            table_id: ID completo da tabela BigQuery.

        Returns:
            Lista de listas com cabeçalhos + dados. Lista vazia se
            tabela não contiver registros.

        Raises:
            Exception: Se a leitura do BigQuery falhar.
        """
        query = f"SELECT * FROM `{table_id}`"
        query_job = self._bq_client.query(query)
        results = query_job.result()

        # Obter nomes das colunas
        headers = [field.name for field in results.schema]

        # Montar dados como lista de listas (headers + rows)
        data = [headers]
        for row in results:
            data.append([self._convert_value(v) for v in row.values()])

        if len(data) == 1:
            # Somente cabeçalho, sem dados
            return []

        return data

    def _write_to_sheet(
        self, spreadsheet_id: str, sheet_name: str, data: list[list]
    ) -> None:
        """Escreve dados na aba da planilha, substituindo conteúdo anterior.

        Abre a planilha pelo ID, seleciona a aba pelo nome, limpa todo o
        conteúdo e escreve os novos dados.

        Args:
            spreadsheet_id: ID da planilha Google Sheets.
            sheet_name: Nome da aba de destino.
            data: Lista de listas com cabeçalhos e dados a serem escritos.

        Raises:
            gspread.exceptions.APIError: Erro da API do Google Sheets.
            requests.exceptions.ConnectionError: Erro de rede.
        """
        spreadsheet = self._gc.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        worksheet.clear()
        worksheet.update(range_name="A1", values=data)

    def _log_export_error(
        self,
        table_id: str,
        spreadsheet_id: str,
        sheet_name: str,
        error: Exception,
    ) -> None:
        """Registra log de erro de exportação com informações completas.

        Args:
            table_id: Nome/ID da tabela BigQuery de origem.
            spreadsheet_id: ID da planilha de destino.
            sheet_name: Nome da aba de destino.
            error: Exceção que causou a falha.
        """
        timestamp = datetime.now().isoformat()
        logger.error(
            "[EXPORTAÇÃO_SHEETS] [FALHA] Tabela: %s | "
            "Planilha: %s | Aba: %s | Timestamp: %s | Erro: %s",
            table_id,
            spreadsheet_id,
            sheet_name,
            timestamp,
            str(error),
        )

    @staticmethod
    def _convert_value(value) -> str | int | float | None:
        """Converte valores do BigQuery para tipos compatíveis com Sheets.

        Valores de tipos complexos (date, datetime, Decimal) são convertidos
        para string para compatibilidade com a API do Google Sheets.

        Args:
            value: Valor retornado pelo BigQuery.

        Returns:
            Valor convertido para tipo compatível com Sheets.
        """
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            return value
        # Para tipos como date, datetime, Decimal etc.
        return str(value)
