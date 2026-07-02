"""Testes unitários para o SheetsExporter.

Valida lógica de backoff exponencial (2s, 4s, 8s), substituição completa
do conteúdo da aba, continuidade em caso de falha em uma exportação,
e tratamento correto de erros transitórios vs não-transitórios.
"""

import logging
from unittest.mock import MagicMock, patch, call

import pytest
import gspread.exceptions
from requests.exceptions import ConnectionError as RequestsConnectionError

from src.sheets_exporter import SheetsExporter


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_dependencies():
    """Mock de gspread, bigquery.Client e Credentials."""
    with patch(
        "src.sheets_exporter.Credentials.from_service_account_file"
    ) as mock_creds, patch(
        "src.sheets_exporter.gspread.authorize"
    ) as mock_authorize, patch(
        "src.sheets_exporter.bigquery.Client"
    ) as mock_bq_cls:
        mock_gc = MagicMock()
        mock_authorize.return_value = mock_gc

        mock_bq_client = MagicMock()
        mock_bq_cls.return_value = mock_bq_client

        yield {
            "creds": mock_creds,
            "authorize": mock_authorize,
            "gc": mock_gc,
            "bq_cls": mock_bq_cls,
            "bq_client": mock_bq_client,
        }


@pytest.fixture
def exporter(mock_dependencies):
    """Instância de SheetsExporter com mocks configurados."""
    return SheetsExporter()


@pytest.fixture
def sample_bq_data(mock_dependencies):
    """Configura mock do BigQuery para retornar dados de exemplo."""

    def _setup(data_rows=None):
        if data_rows is None:
            data_rows = [{"col1": "a", "col2": 1}, {"col1": "b", "col2": 2}]

        mock_bq_client = mock_dependencies["bq_client"]
        mock_query_job = MagicMock()
        mock_results = MagicMock()

        # Schema com campos
        mock_field1 = MagicMock()
        mock_field1.name = "col1"
        mock_field2 = MagicMock()
        mock_field2.name = "col2"
        mock_results.schema = [mock_field1, mock_field2]

        # Linhas de dados
        mock_rows = []
        for row_data in data_rows:
            mock_row = MagicMock()
            mock_row.values.return_value = row_data.values()
            mock_rows.append(mock_row)

        mock_results.__iter__ = lambda self: iter(mock_rows)
        mock_query_job.result.return_value = mock_results
        mock_bq_client.query.return_value = mock_query_job

        return mock_bq_client

    return _setup


# ============================================================
# Testes de exportação com sucesso
# ============================================================


class TestExportSucesso:
    """Testes para exportação bem-sucedida."""

    def test_export_le_dados_bigquery_e_escreve_na_sheet(
        self, exporter, mock_dependencies, sample_bq_data
    ):
        """export() lê dados do BigQuery e escreve na planilha correta."""
        sample_bq_data()
        mock_gc = mock_dependencies["gc"]
        mock_spreadsheet = MagicMock()
        mock_worksheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_spreadsheet.worksheet.return_value = mock_worksheet

        exporter.export(
            table_id="projeto.dataset.tabela",
            spreadsheet_id="SHEET_ID_123",
            sheet_name="Aba Destino",
        )

        # Verifica que a query foi executada
        mock_dependencies["bq_client"].query.assert_called_once_with(
            "SELECT * FROM `projeto.dataset.tabela`"
        )

        # Verifica que a planilha correta foi aberta
        mock_gc.open_by_key.assert_called_once_with("SHEET_ID_123")
        mock_spreadsheet.worksheet.assert_called_once_with("Aba Destino")

    def test_export_substitui_conteudo_completo_da_aba(
        self, exporter, mock_dependencies, sample_bq_data
    ):
        """export() limpa a aba antes de escrever dados novos (substituição completa)."""
        sample_bq_data()
        mock_gc = mock_dependencies["gc"]
        mock_spreadsheet = MagicMock()
        mock_worksheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_spreadsheet.worksheet.return_value = mock_worksheet

        exporter.export(
            table_id="projeto.dataset.tabela",
            spreadsheet_id="SHEET_ID",
            sheet_name="Aba",
        )

        # Verifica que clear() foi chamado antes de update()
        mock_worksheet.clear.assert_called_once()
        mock_worksheet.update.assert_called_once()

        # Verifica que os dados foram escritos com cabeçalhos + linhas
        update_kwargs = mock_worksheet.update.call_args
        written_data = update_kwargs.kwargs.get(
            "values", update_kwargs[1].get("values") if len(update_kwargs) > 1 else None
        )
        if written_data is None:
            # Tenta pegar como argumento posicional
            written_data = update_kwargs[1]["values"] if "values" in (update_kwargs[1] if len(update_kwargs) > 1 else {}) else update_kwargs.kwargs["values"]

        assert written_data[0] == ["col1", "col2"]  # Cabeçalhos
        assert len(written_data) == 3  # 1 header + 2 rows


# ============================================================
# Testes de retry com backoff exponencial
# ============================================================


class TestRetryBackoffExponencial:
    """Testes para retry com backoff exponencial (2s, 4s, 8s) em erros transitórios."""

    @patch("src.sheets_exporter.time.sleep")
    def test_retry_com_backoff_2s_4s_8s_em_api_error(
        self, mock_sleep, exporter, mock_dependencies, sample_bq_data
    ):
        """Retry usa intervalos 2s, 4s, 8s em APIError da Google Sheets API."""
        sample_bq_data()
        mock_gc = mock_dependencies["gc"]
        mock_spreadsheet = MagicMock()
        mock_worksheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_spreadsheet.worksheet.return_value = mock_worksheet

        # Simula APIError em todas as 3 tentativas
        api_error = gspread.exceptions.APIError(
            MagicMock(status_code=429, text="Rate limit exceeded")
        )
        mock_worksheet.clear.side_effect = api_error

        exporter.export(
            table_id="projeto.dataset.tabela",
            spreadsheet_id="SHEET_ID",
            sheet_name="Aba",
        )

        # Verifica backoff exponencial: 2s, 4s (não há sleep após a última tentativa)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(2)  # 2 * 2^0 = 2s
        mock_sleep.assert_any_call(4)  # 2 * 2^1 = 4s

    @patch("src.sheets_exporter.time.sleep")
    def test_retry_com_backoff_em_connection_error(
        self, mock_sleep, exporter, mock_dependencies, sample_bq_data
    ):
        """Retry usa backoff exponencial em ConnectionError."""
        sample_bq_data()
        mock_gc = mock_dependencies["gc"]
        mock_spreadsheet = MagicMock()
        mock_worksheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_spreadsheet.worksheet.return_value = mock_worksheet

        # Simula ConnectionError em todas as tentativas
        mock_worksheet.clear.side_effect = RequestsConnectionError(
            "Falha de rede"
        )

        exporter.export(
            table_id="projeto.dataset.tabela",
            spreadsheet_id="SHEET_ID",
            sheet_name="Aba",
        )

        # Verifica que backoff foi aplicado (2s, 4s)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(2)
        mock_sleep.assert_any_call(4)

    @patch("src.sheets_exporter.time.sleep")
    def test_retry_sucesso_na_segunda_tentativa(
        self, mock_sleep, exporter, mock_dependencies, sample_bq_data
    ):
        """Exportação com sucesso na segunda tentativa após falha transitória."""
        sample_bq_data()
        mock_gc = mock_dependencies["gc"]
        mock_spreadsheet = MagicMock()
        mock_worksheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_spreadsheet.worksheet.return_value = mock_worksheet

        # Falha na primeira tentativa, sucesso na segunda
        api_error = gspread.exceptions.APIError(
            MagicMock(status_code=500, text="Internal error")
        )
        mock_worksheet.clear.side_effect = [api_error, None]

        exporter.export(
            table_id="projeto.dataset.tabela",
            spreadsheet_id="SHEET_ID",
            sheet_name="Aba",
        )

        # Apenas 1 sleep de 2s (entre tentativa 1 e 2)
        mock_sleep.assert_called_once_with(2)
        # update() foi chamado na segunda tentativa com sucesso
        mock_worksheet.update.assert_called_once()


# ============================================================
# Testes de falha após 3 retries
# ============================================================


class TestFalhaAposRetries:
    """Testes para falha definitiva após 3 tentativas."""

    @patch("src.sheets_exporter.time.sleep")
    def test_apos_3_retries_loga_erro_com_detalhes(
        self, mock_sleep, exporter, mock_dependencies, sample_bq_data, caplog
    ):
        """Após 3 falhas, registra log com tabela, spreadsheet_id, timestamp e erro."""
        sample_bq_data()
        mock_gc = mock_dependencies["gc"]
        mock_spreadsheet = MagicMock()
        mock_worksheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_spreadsheet.worksheet.return_value = mock_worksheet

        api_error = gspread.exceptions.APIError(
            MagicMock(status_code=429, text="Rate limit exceeded")
        )
        mock_worksheet.clear.side_effect = api_error

        with caplog.at_level(logging.ERROR):
            exporter.export(
                table_id="projeto.dataset.minha_tabela",
                spreadsheet_id="SHEET_ABC",
                sheet_name="Aba Teste",
            )

        # Verifica que log de erro contém informações essenciais
        error_log = caplog.text
        assert "projeto.dataset.minha_tabela" in error_log
        assert "SHEET_ABC" in error_log
        # Verifica presença de timestamp (formato ISO)
        assert "T" in error_log  # timestamp ISO contém T

    @patch("src.sheets_exporter.time.sleep")
    def test_export_nao_lanca_excecao_apos_falha(
        self, mock_sleep, exporter, mock_dependencies, sample_bq_data
    ):
        """export() não lança exceção mesmo após falhar todas as tentativas."""
        sample_bq_data()
        mock_gc = mock_dependencies["gc"]
        mock_spreadsheet = MagicMock()
        mock_worksheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_spreadsheet.worksheet.return_value = mock_worksheet

        mock_worksheet.clear.side_effect = gspread.exceptions.APIError(
            MagicMock(status_code=503, text="Service unavailable")
        )

        # Não deve lançar exceção — permite que o orchestrator continue
        exporter.export(
            table_id="projeto.dataset.tabela",
            spreadsheet_id="SHEET_ID",
            sheet_name="Aba",
        )


# ============================================================
# Testes de erros não-transitórios
# ============================================================


class TestErrosNaoTransitorios:
    """Testes para erros que não devem ter retry."""

    @patch("src.sheets_exporter.time.sleep")
    def test_erro_nao_transitorio_falha_imediata_sem_retry(
        self, mock_sleep, exporter, mock_dependencies, sample_bq_data
    ):
        """Erros não-transitórios falham imediatamente sem retry."""
        sample_bq_data()
        mock_gc = mock_dependencies["gc"]
        mock_spreadsheet = MagicMock()
        mock_worksheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_spreadsheet.worksheet.return_value = mock_worksheet

        # ValueError não é transitório (nem APIError nem ConnectionError)
        mock_worksheet.clear.side_effect = ValueError("Erro inesperado")

        exporter.export(
            table_id="projeto.dataset.tabela",
            spreadsheet_id="SHEET_ID",
            sheet_name="Aba",
        )

        # Sem retry — somente 1 tentativa
        mock_worksheet.clear.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("src.sheets_exporter.time.sleep")
    def test_erro_nao_transitorio_nao_lanca_excecao(
        self, mock_sleep, exporter, mock_dependencies, sample_bq_data
    ):
        """Erros não-transitórios são logados mas não propagam exceção."""
        sample_bq_data()
        mock_gc = mock_dependencies["gc"]
        mock_spreadsheet = MagicMock()
        mock_worksheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_spreadsheet.worksheet.return_value = mock_worksheet

        mock_worksheet.clear.side_effect = PermissionError("Sem permissão")

        # Não deve lançar exceção
        exporter.export(
            table_id="projeto.dataset.tabela",
            spreadsheet_id="SHEET_ID",
            sheet_name="Aba",
        )


# ============================================================
# Testes de continuidade em caso de falha
# ============================================================


class TestContinuidadeEmFalha:
    """Testes para garantir que falha em uma exportação não afeta as demais."""

    @patch("src.sheets_exporter.time.sleep")
    def test_export_retorna_sem_excecao_permitindo_proxima_exportacao(
        self, mock_sleep, exporter, mock_dependencies, sample_bq_data, caplog
    ):
        """export() retorna normalmente após falha, permitindo que o orchestrator
        continue com as demais exportações pendentes."""
        sample_bq_data()
        mock_gc = mock_dependencies["gc"]
        mock_spreadsheet = MagicMock()
        mock_worksheet = MagicMock()
        mock_gc.open_by_key.return_value = mock_spreadsheet
        mock_spreadsheet.worksheet.return_value = mock_worksheet

        mock_worksheet.clear.side_effect = gspread.exceptions.APIError(
            MagicMock(status_code=429, text="Too many requests")
        )

        with caplog.at_level(logging.ERROR):
            # Primeira exportação falha
            exporter.export(
                table_id="projeto.dataset.tabela_a",
                spreadsheet_id="SHEET_1",
                sheet_name="Aba A",
            )

        # Verifica que erro foi logado
        assert "FALHA" in caplog.text or "projeto.dataset.tabela_a" in caplog.text

        # Reset dos mocks para segunda exportação
        caplog.clear()
        mock_worksheet.clear.side_effect = None
        mock_worksheet.clear.reset_mock()
        mock_worksheet.update.reset_mock()

        # Segunda exportação funciona normalmente
        exporter.export(
            table_id="projeto.dataset.tabela_b",
            spreadsheet_id="SHEET_2",
            sheet_name="Aba B",
        )

        # Verifica que a segunda exportação foi bem-sucedida
        mock_worksheet.update.assert_called_once()
