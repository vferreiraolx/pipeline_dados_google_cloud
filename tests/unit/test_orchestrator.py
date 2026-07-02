"""
Testes unitários do Orchestrator.

Testa o fluxo completo do pipeline com mocks de todos os componentes,
validando tratamento de falhas parciais, relatório de execução e
comportamento de abort em caso de falha de conexão/configuração.
"""

from unittest.mock import MagicMock, patch, mock_open

import pytest

from src.orchestrator import Orchestrator
from src.config_manager import ConfigManager
from src.exceptions import ConfigValidationError, CredentialError
from src.models import DerivedTableConfig, SheetsMappingConfig, SourceTableConfig


@pytest.fixture
def mock_config():
    """Cria um mock do ConfigManager com configuração válida."""
    config = MagicMock(spec=ConfigManager)
    config.project_id = "conect-python-g-sheets"
    config.bucket_name = "teste-extracao-trino"
    config.config = {"bigquery": {"dataset": "planejamento_comercial"}}
    config._config_path = "/fake/config.yaml"

    config.get_source_tables.return_value = [
        SourceTableConfig(
            full_name="hive.planejamento.re_gold_receita_unificado_air",
            short_name="re_gold_receita_unificado_air",
            partition_column="dt",
        ),
        SourceTableConfig(
            full_name="hive.planejamento.re_silver_receita_cb_air",
            short_name="re_silver_receita_cb_air",
            partition_column="dt",
        ),
    ]

    config.get_derived_tables.return_value = [
        DerivedTableConfig(
            name="receita_consolidada",
            destination="conect-python-g-sheets.planejamento_comercial.receita_consolidada",
            order=1,
            sql_file="sql/receita_consolidada.sql",
        ),
    ]

    config.get_sheets_mappings.return_value = [
        SheetsMappingConfig(
            table="conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air",
            spreadsheet_id="1ABC",
            sheet_name="Receita Unificado",
        ),
    ]

    return config


class TestOrchestratorInit:
    """Testes de inicialização do Orchestrator."""

    def test_init_with_config(self, mock_config):
        """Orchestrator inicializa com ConfigManager."""
        orch = Orchestrator(mock_config)
        assert orch.config == mock_config


class TestOrchestratorConnectionFailure:
    """Testes de falha na conexão com Trino."""

    @patch("src.orchestrator.TrinoExtractor")
    def test_credential_error_aborts_run(self, mock_trino_cls, mock_config):
        """Se credenciais estão ausentes, aborta com relatório de falha."""
        mock_trino_cls.side_effect = CredentialError("TRINO_USER ausente")

        orch = Orchestrator(mock_config)
        report = orch.run()

        assert report["overall_status"] == "falha"
        assert report["stages"]["conexao_trino"] == "falha"
        assert report["tables_processed"] == []

    @patch("src.orchestrator.TrinoExtractor")
    def test_connection_error_aborts_run(self, mock_trino_cls, mock_config):
        """Se conexão Trino falha após retries, aborta com relatório."""
        mock_trino_instance = MagicMock()
        mock_trino_instance.connect.side_effect = ConnectionError(
            "Falha após 3 tentativas"
        )
        mock_trino_cls.return_value = mock_trino_instance

        orch = Orchestrator(mock_config)
        report = orch.run()

        assert report["overall_status"] == "falha"
        assert report["stages"]["conexao_trino"] == "falha"
        mock_trino_instance.connect.assert_called_once()


class TestOrchestratorFullFlow:
    """Testes do fluxo completo com sucesso."""

    @patch("src.orchestrator.SheetsExporter")
    @patch("src.orchestrator.StateManager")
    @patch("src.orchestrator.BigQueryLoader")
    @patch("src.orchestrator.GCSUploader")
    @patch("src.orchestrator.TrinoExtractor")
    @patch("builtins.open", mock_open(read_data="SELECT * FROM tabela"))
    @patch("os.path.isfile", return_value=True)
    @patch("os.makedirs")
    def test_full_success_flow(
        self,
        mock_makedirs,
        mock_isfile,
        mock_trino_cls,
        mock_gcs_cls,
        mock_bq_cls,
        mock_state_cls,
        mock_sheets_cls,
        mock_config,
    ):
        """Fluxo completo com sucesso retorna relatório correto."""
        # Setup mocks
        mock_trino = MagicMock()
        mock_trino_cls.return_value = mock_trino
        mock_trino.extract_full.return_value = 1000
        mock_trino.extract_incremental.return_value = 50

        mock_gcs = MagicMock()
        mock_gcs_cls.return_value = mock_gcs

        mock_bq = MagicMock()
        mock_bq_cls.return_value = mock_bq

        mock_state = MagicMock()
        mock_state_cls.return_value = mock_state
        mock_state.is_first_load.side_effect = [True, False]

        mock_sheets = MagicMock()
        mock_sheets_cls.return_value = mock_sheets

        orch = Orchestrator(mock_config)
        report = orch.run()

        # Verificações
        assert report["overall_status"] == "sucesso"
        assert len(report["tables_processed"]) == 2
        assert report["tables_failed"] == []
        assert report["stages"]["conexao_trino"] == "sucesso"
        assert report["stages"]["extracao"] == "sucesso"
        assert report["stages"]["upload_gcs"] == "sucesso"
        assert report["stages"]["carga_bigquery"] == "sucesso"
        assert report["stages"]["tabelas_derivadas"] == "sucesso"
        assert report["stages"]["exportacao_sheets"] == "sucesso"

        # Trino sempre fechado
        mock_trino.close.assert_called_once()

        # Primeira tabela: full, segunda: incremental
        mock_trino.extract_full.assert_called_once()
        mock_trino.extract_incremental.assert_called_once()

        # State registrado para ambas
        assert mock_state.mark_loaded.call_count == 2


class TestOrchestratorPartialFailure:
    """Testes de falha parcial — pipeline continua."""

    @patch("src.orchestrator.SheetsExporter")
    @patch("src.orchestrator.StateManager")
    @patch("src.orchestrator.BigQueryLoader")
    @patch("src.orchestrator.GCSUploader")
    @patch("src.orchestrator.TrinoExtractor")
    @patch("builtins.open", mock_open(read_data="SELECT * FROM tabela"))
    @patch("os.path.isfile", return_value=True)
    @patch("os.makedirs")
    def test_extraction_failure_skips_table(
        self,
        mock_makedirs,
        mock_isfile,
        mock_trino_cls,
        mock_gcs_cls,
        mock_bq_cls,
        mock_state_cls,
        mock_sheets_cls,
        mock_config,
    ):
        """Falha na extração de uma tabela não interrompe as demais."""
        mock_trino = MagicMock()
        mock_trino_cls.return_value = mock_trino
        # Primeira tabela falha, segunda tem sucesso
        mock_trino.extract_full.side_effect = Exception("Timeout")
        mock_trino.extract_incremental.return_value = 50

        mock_gcs = MagicMock()
        mock_gcs_cls.return_value = mock_gcs

        mock_bq = MagicMock()
        mock_bq_cls.return_value = mock_bq

        mock_state = MagicMock()
        mock_state_cls.return_value = mock_state
        mock_state.is_first_load.side_effect = [True, False]

        mock_sheets = MagicMock()
        mock_sheets_cls.return_value = mock_sheets

        orch = Orchestrator(mock_config)
        report = orch.run()

        assert report["overall_status"] == "falha_parcial"
        assert len(report["tables_processed"]) == 1
        assert len(report["tables_failed"]) == 1
        assert report["tables_failed"][0]["stage"] == "extração"

        # Trino é fechado mesmo com falha
        mock_trino.close.assert_called_once()

    @patch("src.orchestrator.SheetsExporter")
    @patch("src.orchestrator.StateManager")
    @patch("src.orchestrator.BigQueryLoader")
    @patch("src.orchestrator.GCSUploader")
    @patch("src.orchestrator.TrinoExtractor")
    @patch("builtins.open", mock_open(read_data="SELECT * FROM tabela"))
    @patch("os.path.isfile", return_value=True)
    @patch("os.makedirs")
    def test_derived_table_failure_continues(
        self,
        mock_makedirs,
        mock_isfile,
        mock_trino_cls,
        mock_gcs_cls,
        mock_bq_cls,
        mock_state_cls,
        mock_sheets_cls,
        mock_config,
    ):
        """Falha em tabela derivada não interrompe exportação Sheets."""
        mock_trino = MagicMock()
        mock_trino_cls.return_value = mock_trino
        mock_trino.extract_full.return_value = 100
        mock_trino.extract_incremental.return_value = 50

        mock_gcs = MagicMock()
        mock_gcs_cls.return_value = mock_gcs

        mock_bq = MagicMock()
        mock_bq_cls.return_value = mock_bq
        # Tabela derivada falha
        mock_bq.execute_derived_table.side_effect = Exception("SQL inválido")

        mock_state = MagicMock()
        mock_state_cls.return_value = mock_state
        mock_state.is_first_load.side_effect = [True, False]

        mock_sheets = MagicMock()
        mock_sheets_cls.return_value = mock_sheets

        orch = Orchestrator(mock_config)
        report = orch.run()

        # Pipeline continua apesar da falha na derivada
        assert report["stages"]["tabelas_derivadas"] == "falha_parcial"
        assert report["stages"]["exportacao_sheets"] == "sucesso"
        mock_sheets.export.assert_called_once()


class TestOrchestratorTrinoAlwaysClosed:
    """Testa que conexão Trino é sempre fechada."""

    @patch("src.orchestrator.SheetsExporter")
    @patch("src.orchestrator.StateManager")
    @patch("src.orchestrator.BigQueryLoader")
    @patch("src.orchestrator.GCSUploader")
    @patch("src.orchestrator.TrinoExtractor")
    @patch("builtins.open", mock_open(read_data="SELECT 1"))
    @patch("os.path.isfile", return_value=True)
    @patch("os.makedirs")
    def test_trino_closed_on_extraction_crash(
        self,
        mock_makedirs,
        mock_isfile,
        mock_trino_cls,
        mock_gcs_cls,
        mock_bq_cls,
        mock_state_cls,
        mock_sheets_cls,
        mock_config,
    ):
        """Conexão Trino é fechada mesmo quando todas as extrações falham."""
        mock_trino = MagicMock()
        mock_trino_cls.return_value = mock_trino
        mock_trino.extract_full.side_effect = Exception("Erro fatal")
        mock_trino.extract_incremental.side_effect = Exception("Erro fatal")

        mock_state = MagicMock()
        mock_state_cls.return_value = mock_state
        mock_state.is_first_load.return_value = True

        mock_gcs_cls.return_value = MagicMock()
        mock_bq_cls.return_value = MagicMock()
        mock_sheets_cls.return_value = MagicMock()

        orch = Orchestrator(mock_config)
        orch.run()

        mock_trino.close.assert_called_once()
