"""Testes unitários para o StateManager.

Valida a lógica de controle de estado de extração: verificação de primeira
carga (is_first_load), registro de extração (mark_loaded) e criação da
tabela de estado no BigQuery.
"""

from unittest.mock import MagicMock, patch, call

import pytest

from src.state_manager import StateManager


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_bq_client():
    """Mock do google.cloud.bigquery.Client e módulo bigquery."""
    with patch("src.state_manager.bigquery.Client") as mock_client_cls, \
         patch("src.state_manager.bigquery.DatasetReference") as mock_dataset_ref_cls, \
         patch("src.state_manager.bigquery.Dataset") as mock_dataset_cls, \
         patch("src.state_manager.bigquery.SchemaField") as mock_schema_field, \
         patch("src.state_manager.bigquery.Table") as mock_table_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        yield {
            "client_cls": mock_client_cls,
            "client": mock_client,
            "dataset_ref_cls": mock_dataset_ref_cls,
            "dataset_cls": mock_dataset_cls,
            "schema_field": mock_schema_field,
            "table_cls": mock_table_cls,
        }


@pytest.fixture
def manager(mock_bq_client):
    """Instância de StateManager com mocks do BigQuery."""
    return StateManager(
        project="conect-python-g-sheets",
        dataset="pipeline_metadata",
    )


# ============================================================
# Testes de inicialização
# ============================================================


class TestStateManagerInit:
    """Testes de inicialização do StateManager."""

    def test_inicializa_com_projeto_padrao(self, mock_bq_client):
        """StateManager inicializa com projeto padrão."""
        sm = StateManager()
        assert sm.project == "conect-python-g-sheets"

    def test_inicializa_com_dataset_padrao(self, mock_bq_client):
        """StateManager inicializa com dataset padrão pipeline_metadata."""
        sm = StateManager()
        assert sm.dataset == "pipeline_metadata"

    def test_inicializa_com_projeto_custom(self, mock_bq_client):
        """StateManager aceita projeto customizado."""
        sm = StateManager(project="meu-projeto", dataset="meu_dataset")
        assert sm.project == "meu-projeto"
        assert sm.dataset == "meu_dataset"

    def test_cria_cliente_com_projeto(self, mock_bq_client):
        """Cliente BigQuery é criado com o projeto especificado."""
        StateManager(project="conect-python-g-sheets")
        mock_bq_client["client_cls"].assert_called_once_with(
            project="conect-python-g-sheets"
        )

    def test_ensure_table_exists_chamado_na_init(self, mock_bq_client):
        """_ensure_table_exists é chamado durante __init__ (cria tabela se necessário)."""
        StateManager()
        # Verifica que create_table foi chamado (parte de _ensure_table_exists)
        mock_bq_client["client"].create_table.assert_called_once()

    def test_ensure_table_exists_cria_dataset_se_nao_existe(self, mock_bq_client):
        """_ensure_table_exists cria dataset se get_dataset lança exceção."""
        mock_bq_client["client"].get_dataset.side_effect = Exception("Not found")
        StateManager()
        mock_bq_client["client"].create_dataset.assert_called_once()

    def test_table_id_formato_correto(self, mock_bq_client):
        """_table_id segue formato projeto.dataset.tabela."""
        sm = StateManager(project="proj", dataset="ds")
        assert sm._table_id == "proj.ds.extraction_state"


# ============================================================
# Testes de is_first_load
# ============================================================


class TestIsFirstLoad:
    """Testes para verificação de primeira carga."""

    def test_retorna_true_quando_nao_existe_extracao(self, manager, mock_bq_client):
        """is_first_load retorna True quando não há extração anterior com sucesso."""
        mock_query_job = MagicMock()
        mock_row = MagicMock()
        mock_row.total = 0
        mock_query_job.result.return_value = [mock_row]
        mock_bq_client["client"].query.return_value = mock_query_job

        result = manager.is_first_load("re_gold_receita_unificado_air")
        assert result is True

    def test_retorna_false_quando_existe_extracao_anterior(
        self, manager, mock_bq_client
    ):
        """is_first_load retorna False quando já existe extração com sucesso."""
        mock_query_job = MagicMock()
        mock_row = MagicMock()
        mock_row.total = 3
        mock_query_job.result.return_value = [mock_row]
        mock_bq_client["client"].query.return_value = mock_query_job

        result = manager.is_first_load("re_gold_receita_unificado_air")
        assert result is False

    def test_usa_parametro_table_name_na_query(self, manager, mock_bq_client):
        """is_first_load usa query parametrizada com table_name."""
        mock_query_job = MagicMock()
        mock_row = MagicMock()
        mock_row.total = 0
        mock_query_job.result.return_value = [mock_row]
        mock_bq_client["client"].query.return_value = mock_query_job

        manager.is_first_load("re_silver_receita_cb_air")

        # Verifica que query foi chamada
        mock_bq_client["client"].query.assert_called_once()
        call_args = mock_bq_client["client"].query.call_args

        # Verifica que a query filtra por status='success'
        query_text = call_args[0][0]
        assert "status = 'success'" in query_text
        assert "table_name = @table_name" in query_text

    def test_retorna_true_em_caso_de_excecao(self, manager, mock_bq_client):
        """is_first_load retorna True (segurança) quando ocorre exceção."""
        mock_bq_client["client"].query.side_effect = Exception("Erro de consulta")

        result = manager.is_first_load("tabela_qualquer")
        assert result is True


# ============================================================
# Testes de mark_loaded
# ============================================================


class TestMarkLoaded:
    """Testes para registro de extração concluída."""

    def test_insere_registro_com_dados_corretos(self, manager, mock_bq_client):
        """mark_loaded insere registro com todos os campos preenchidos."""
        mock_bq_client["client"].insert_rows_json.return_value = []

        manager.mark_loaded(
            table_name="re_gold_receita_unificado_air",
            load_date="2024-01-15",
            rows_count=45230,
            extraction_type="full",
            status="success",
        )

        mock_bq_client["client"].insert_rows_json.assert_called_once()
        call_args = mock_bq_client["client"].insert_rows_json.call_args

        table_id = call_args[0][0]
        rows = call_args[0][1]

        assert table_id == "conect-python-g-sheets.pipeline_metadata.extraction_state"
        assert len(rows) == 1
        row = rows[0]
        assert row["table_name"] == "re_gold_receita_unificado_air"
        assert row["last_extraction_date"] == "2024-01-15"
        assert row["rows_extracted"] == 45230
        assert row["extraction_type"] == "full"
        assert row["status"] == "success"
        assert "updated_at" in row

    def test_mark_loaded_com_valores_padrao(self, manager, mock_bq_client):
        """mark_loaded usa extraction_type='incremental' e status='success' como padrão."""
        mock_bq_client["client"].insert_rows_json.return_value = []

        manager.mark_loaded(
            table_name="re_silver_receita_cb_air",
            load_date="2024-03-20",
            rows_count=1000,
        )

        call_args = mock_bq_client["client"].insert_rows_json.call_args
        row = call_args[0][1][0]
        assert row["extraction_type"] == "incremental"
        assert row["status"] == "success"

    def test_mark_loaded_nao_lanca_excecao_em_falha(self, manager, mock_bq_client):
        """mark_loaded não propaga exceção em caso de falha de inserção."""
        mock_bq_client["client"].insert_rows_json.side_effect = Exception(
            "Erro de inserção"
        )

        # Não deve lançar exceção
        manager.mark_loaded(
            table_name="tabela_teste",
            load_date="2024-01-01",
            rows_count=100,
        )

    def test_mark_loaded_loga_erro_quando_insert_retorna_erros(
        self, manager, mock_bq_client
    ):
        """mark_loaded loga erro quando insert_rows_json retorna lista de erros."""
        mock_bq_client["client"].insert_rows_json.return_value = [
            {"index": 0, "errors": [{"reason": "invalidQuery"}]}
        ]

        # Não deve lançar exceção, mas o erro será logado
        manager.mark_loaded(
            table_name="tabela_teste",
            load_date="2024-01-01",
            rows_count=50,
        )

    def test_mark_loaded_com_status_failed(self, manager, mock_bq_client):
        """mark_loaded aceita status='failed' para registrar falhas."""
        mock_bq_client["client"].insert_rows_json.return_value = []

        manager.mark_loaded(
            table_name="tabela_falha",
            load_date="2024-02-10",
            rows_count=0,
            extraction_type="incremental",
            status="failed",
        )

        call_args = mock_bq_client["client"].insert_rows_json.call_args
        row = call_args[0][1][0]
        assert row["status"] == "failed"
        assert row["rows_extracted"] == 0
