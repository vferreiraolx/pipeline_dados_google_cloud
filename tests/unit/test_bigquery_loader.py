"""Testes unitários para o BigQueryLoader.

Valida carga completa (WRITE_TRUNCATE), carga incremental (DELETE por dt + INSERT),
execução de tabelas derivadas e tratamento de falhas por tabela.
"""

from unittest.mock import MagicMock, patch, call

import pytest

from src.bigquery_loader import BigQueryLoader


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_bq_client():
    """Mock do google.cloud.bigquery.Client."""
    with patch("src.bigquery_loader.bigquery.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        yield {
            "client_cls": mock_client_cls,
            "client": mock_client,
        }


@pytest.fixture
def loader(mock_bq_client):
    """Instância de BigQueryLoader com mock do Client."""
    return BigQueryLoader(project="conect-python-g-sheets")


# ============================================================
# Testes de inicialização
# ============================================================


class TestBigQueryLoaderInit:
    """Testes de inicialização do BigQueryLoader."""

    def test_inicializa_com_projeto_padrao(self, mock_bq_client):
        """BigQueryLoader inicializa com projeto padrão."""
        loader = BigQueryLoader()
        assert loader.project == "conect-python-g-sheets"

    def test_inicializa_com_projeto_custom(self, mock_bq_client):
        """BigQueryLoader aceita projeto customizado."""
        loader = BigQueryLoader(project="meu-projeto")
        assert loader.project == "meu-projeto"

    def test_cria_cliente_com_projeto(self, mock_bq_client):
        """Cliente BigQuery é criado com o projeto especificado."""
        BigQueryLoader(project="conect-python-g-sheets")
        mock_bq_client["client_cls"].assert_called_once_with(
            project="conect-python-g-sheets"
        )


# ============================================================
# Testes de load_full (WRITE_TRUNCATE)
# ============================================================


class TestLoadFull:
    """Testes para carga completa com WRITE_TRUNCATE."""

    @patch("src.bigquery_loader.bigquery.LoadJobConfig")
    def test_load_full_usa_write_truncate(
        self, mock_job_config_cls, loader, mock_bq_client
    ):
        """load_full configura WriteDisposition como WRITE_TRUNCATE."""
        mock_job_config = MagicMock()
        mock_job_config_cls.return_value = mock_job_config

        mock_load_job = MagicMock()
        mock_bq_client["client"].load_table_from_uri.return_value = mock_load_job

        mock_table = MagicMock()
        mock_table.num_rows = 100
        mock_bq_client["client"].get_table.return_value = mock_table

        loader.load_full(
            gcs_uri="gs://bucket/tabela/tabela_2024-01-15.csv",
            table_id="projeto.dataset.tabela",
        )

        # Verifica que LoadJobConfig foi chamado com WRITE_TRUNCATE
        from google.cloud import bigquery as bq_module

        mock_job_config_cls.assert_called_once()
        config_kwargs = mock_job_config_cls.call_args[1]
        assert config_kwargs["write_disposition"] == bq_module.WriteDisposition.WRITE_TRUNCATE

    @patch("src.bigquery_loader.bigquery.LoadJobConfig")
    def test_load_full_usa_autodetect(
        self, mock_job_config_cls, loader, mock_bq_client
    ):
        """load_full configura autodetect=True para detecção automática de schema."""
        mock_job_config = MagicMock()
        mock_job_config_cls.return_value = mock_job_config

        mock_load_job = MagicMock()
        mock_bq_client["client"].load_table_from_uri.return_value = mock_load_job

        mock_table = MagicMock()
        mock_table.num_rows = 50
        mock_bq_client["client"].get_table.return_value = mock_table

        loader.load_full(
            gcs_uri="gs://bucket/tabela/tabela_2024-01-15.csv",
            table_id="projeto.dataset.tabela",
        )

        config_kwargs = mock_job_config_cls.call_args[1]
        assert config_kwargs["autodetect"] is True

    @patch("src.bigquery_loader.bigquery.LoadJobConfig")
    def test_load_full_chama_load_table_from_uri(
        self, mock_job_config_cls, loader, mock_bq_client
    ):
        """load_full chama client.load_table_from_uri com URI e table_id corretos."""
        mock_job_config = MagicMock()
        mock_job_config_cls.return_value = mock_job_config

        mock_load_job = MagicMock()
        mock_bq_client["client"].load_table_from_uri.return_value = mock_load_job

        mock_table = MagicMock()
        mock_table.num_rows = 200
        mock_bq_client["client"].get_table.return_value = mock_table

        loader.load_full(
            gcs_uri="gs://bucket/tabela/tabela_2024-01-15.csv",
            table_id="projeto.dataset.tabela",
        )

        mock_bq_client["client"].load_table_from_uri.assert_called_once_with(
            "gs://bucket/tabela/tabela_2024-01-15.csv",
            "projeto.dataset.tabela",
            job_config=mock_job_config,
        )
        mock_load_job.result.assert_called_once()

    @patch("src.bigquery_loader.bigquery.LoadJobConfig")
    def test_load_full_nao_lanca_excecao_em_falha(
        self, mock_job_config_cls, loader, mock_bq_client
    ):
        """load_full não propaga exceção em caso de falha (registra via log)."""
        mock_job_config = MagicMock()
        mock_job_config_cls.return_value = mock_job_config

        mock_load_job = MagicMock()
        mock_load_job.result.side_effect = Exception("Erro de carga BigQuery")
        mock_bq_client["client"].load_table_from_uri.return_value = mock_load_job

        # Não deve lançar exceção
        loader.load_full(
            gcs_uri="gs://bucket/tabela/tabela_2024-01-15.csv",
            table_id="projeto.dataset.tabela",
        )


# ============================================================
# Testes de load_incremental (DELETE por dt + INSERT)
# ============================================================


class TestLoadIncremental:
    """Testes para carga incremental com deduplicação por dt."""

    @patch("src.bigquery_loader.bigquery.LoadJobConfig")
    def test_load_incremental_extrai_data_do_uri(
        self, mock_job_config_cls, loader, mock_bq_client
    ):
        """load_incremental extrai data do padrão tabela_YYYY-MM-DD.csv no URI."""
        mock_job_config = MagicMock()
        mock_job_config_cls.return_value = mock_job_config

        mock_query_job = MagicMock()
        mock_bq_client["client"].query.return_value = mock_query_job

        mock_load_job = MagicMock()
        mock_bq_client["client"].load_table_from_uri.return_value = mock_load_job

        mock_table = MagicMock()
        mock_table.num_rows = 500
        mock_bq_client["client"].get_table.return_value = mock_table

        loader.load_incremental(
            gcs_uri="gs://bucket/tabela/tabela_2024-03-20.csv",
            table_id="projeto.dataset.tabela",
        )

        # Verifica que o DELETE usa a data extraída do URI
        delete_call = mock_bq_client["client"].query.call_args[0][0]
        assert "2024-03-20" in delete_call
        assert "DELETE FROM" in delete_call

    @patch("src.bigquery_loader.bigquery.LoadJobConfig")
    def test_load_incremental_executa_delete_antes_do_load(
        self, mock_job_config_cls, loader, mock_bq_client
    ):
        """load_incremental executa DELETE antes do LOAD (deduplicação)."""
        mock_job_config = MagicMock()
        mock_job_config_cls.return_value = mock_job_config

        mock_query_job = MagicMock()
        mock_bq_client["client"].query.return_value = mock_query_job

        mock_load_job = MagicMock()
        mock_bq_client["client"].load_table_from_uri.return_value = mock_load_job

        mock_table = MagicMock()
        mock_table.num_rows = 300
        mock_bq_client["client"].get_table.return_value = mock_table

        loader.load_incremental(
            gcs_uri="gs://bucket/tabela/tabela_2024-01-15.csv",
            table_id="projeto.dataset.tabela",
        )

        # DELETE é chamado via query
        mock_bq_client["client"].query.assert_called_once()
        mock_query_job.result.assert_called_once()

        # LOAD é chamado depois do DELETE
        mock_bq_client["client"].load_table_from_uri.assert_called_once()
        mock_load_job.result.assert_called_once()

    @patch("src.bigquery_loader.bigquery.LoadJobConfig")
    def test_load_incremental_usa_write_append(
        self, mock_job_config_cls, loader, mock_bq_client
    ):
        """load_incremental configura WriteDisposition como WRITE_APPEND."""
        mock_job_config = MagicMock()
        mock_job_config_cls.return_value = mock_job_config

        mock_query_job = MagicMock()
        mock_bq_client["client"].query.return_value = mock_query_job

        mock_load_job = MagicMock()
        mock_bq_client["client"].load_table_from_uri.return_value = mock_load_job

        mock_table = MagicMock()
        mock_table.num_rows = 150
        mock_bq_client["client"].get_table.return_value = mock_table

        loader.load_incremental(
            gcs_uri="gs://bucket/tabela/tabela_2024-01-15.csv",
            table_id="projeto.dataset.tabela",
        )

        from google.cloud import bigquery as bq_module

        config_kwargs = mock_job_config_cls.call_args[1]
        assert config_kwargs["write_disposition"] == bq_module.WriteDisposition.WRITE_APPEND

    @patch("src.bigquery_loader.bigquery.LoadJobConfig")
    def test_load_incremental_usa_coluna_particao_customizada(
        self, mock_job_config_cls, loader, mock_bq_client
    ):
        """load_incremental usa partition_column informada na query DELETE."""
        mock_job_config = MagicMock()
        mock_job_config_cls.return_value = mock_job_config

        mock_query_job = MagicMock()
        mock_bq_client["client"].query.return_value = mock_query_job

        mock_load_job = MagicMock()
        mock_bq_client["client"].load_table_from_uri.return_value = mock_load_job

        mock_table = MagicMock()
        mock_table.num_rows = 75
        mock_bq_client["client"].get_table.return_value = mock_table

        loader.load_incremental(
            gcs_uri="gs://bucket/tabela/tabela_2024-06-10.csv",
            table_id="projeto.dataset.tabela",
            partition_column="data_referencia",
        )

        delete_call = mock_bq_client["client"].query.call_args[0][0]
        assert "data_referencia" in delete_call
        assert "2024-06-10" in delete_call

    @patch("src.bigquery_loader.bigquery.LoadJobConfig")
    def test_load_incremental_nao_lanca_excecao_em_falha(
        self, mock_job_config_cls, loader, mock_bq_client
    ):
        """load_incremental não propaga exceção em caso de falha."""
        mock_job_config = MagicMock()
        mock_job_config_cls.return_value = mock_job_config

        mock_query_job = MagicMock()
        mock_query_job.result.side_effect = Exception("Erro ao executar DELETE")
        mock_bq_client["client"].query.return_value = mock_query_job

        # Não deve lançar exceção
        loader.load_incremental(
            gcs_uri="gs://bucket/tabela/tabela_2024-01-15.csv",
            table_id="projeto.dataset.tabela",
        )

    def test_load_incremental_retorna_sem_erro_quando_data_nao_encontrada(
        self, loader, mock_bq_client
    ):
        """load_incremental retorna silenciosamente se não extrair data do URI."""
        # URI sem padrão de data válido
        loader.load_incremental(
            gcs_uri="gs://bucket/tabela/arquivo_sem_data.txt",
            table_id="projeto.dataset.tabela",
        )

        # Não deve chamar query nem load
        mock_bq_client["client"].query.assert_not_called()
        mock_bq_client["client"].load_table_from_uri.assert_not_called()


# ============================================================
# Testes de execute_derived_table
# ============================================================


class TestExecuteDerivedTable:
    """Testes para execução de tabelas derivadas via SQL."""

    @patch("src.bigquery_loader.bigquery.QueryJobConfig")
    def test_execute_derived_table_usa_write_truncate(
        self, mock_query_config_cls, loader, mock_bq_client
    ):
        """execute_derived_table configura WRITE_TRUNCATE no destino."""
        mock_query_config = MagicMock()
        mock_query_config_cls.return_value = mock_query_config

        mock_query_job = MagicMock()
        mock_bq_client["client"].query.return_value = mock_query_job

        mock_table = MagicMock()
        mock_table.num_rows = 1000
        mock_bq_client["client"].get_table.return_value = mock_table

        loader.execute_derived_table(
            query="SELECT * FROM tabela_base",
            destination_table="projeto.dataset.tabela_derivada",
        )

        from google.cloud import bigquery as bq_module

        mock_query_config_cls.assert_called_once_with(
            destination="projeto.dataset.tabela_derivada",
            write_disposition=bq_module.WriteDisposition.WRITE_TRUNCATE,
        )

    @patch("src.bigquery_loader.bigquery.QueryJobConfig")
    def test_execute_derived_table_executa_query_com_config(
        self, mock_query_config_cls, loader, mock_bq_client
    ):
        """execute_derived_table passa query e job_config para client.query."""
        mock_query_config = MagicMock()
        mock_query_config_cls.return_value = mock_query_config

        mock_query_job = MagicMock()
        mock_bq_client["client"].query.return_value = mock_query_job

        mock_table = MagicMock()
        mock_table.num_rows = 500
        mock_bq_client["client"].get_table.return_value = mock_table

        sql = "SELECT col1, SUM(col2) FROM tabela GROUP BY col1"
        loader.execute_derived_table(
            query=sql,
            destination_table="projeto.dataset.resultado",
        )

        mock_bq_client["client"].query.assert_called_once_with(
            sql, job_config=mock_query_config
        )
        mock_query_job.result.assert_called_once()

    @patch("src.bigquery_loader.bigquery.QueryJobConfig")
    def test_execute_derived_table_nao_lanca_excecao_em_falha(
        self, mock_query_config_cls, loader, mock_bq_client
    ):
        """execute_derived_table não propaga exceção em caso de falha."""
        mock_query_config = MagicMock()
        mock_query_config_cls.return_value = mock_query_config

        mock_query_job = MagicMock()
        mock_query_job.result.side_effect = Exception("SQL inválido")
        mock_bq_client["client"].query.return_value = mock_query_job

        # Não deve lançar exceção
        loader.execute_derived_table(
            query="SELECT INVALID SYNTAX",
            destination_table="projeto.dataset.tabela_derivada",
        )


# ============================================================
# Testes de _extract_date_from_uri
# ============================================================


class TestExtractDateFromUri:
    """Testes para extração de data do URI do GCS."""

    def test_extrai_data_de_uri_padrao(self, loader):
        """Extrai data no formato YYYY-MM-DD de URI padrão."""
        uri = "gs://bucket/tabela/tabela_2024-01-15.csv"
        assert loader._extract_date_from_uri(uri) == "2024-01-15"

    def test_extrai_data_com_path_complexo(self, loader):
        """Extrai data mesmo com path com múltiplos segmentos."""
        uri = "gs://bucket/subdir/tabela/tabela_nome_2023-12-31.csv"
        assert loader._extract_date_from_uri(uri) == "2023-12-31"

    def test_retorna_none_quando_nao_encontra_data(self, loader):
        """Retorna None quando URI não contém padrão de data."""
        uri = "gs://bucket/tabela/arquivo_sem_data.csv"
        assert loader._extract_date_from_uri(uri) is None

    def test_retorna_none_para_uri_sem_extensao_csv(self, loader):
        """Retorna None quando URI não termina em .csv com data."""
        uri = "gs://bucket/tabela/tabela_2024-01-15.parquet"
        assert loader._extract_date_from_uri(uri) is None

    def test_extrai_data_formato_correto_com_zeros(self, loader):
        """Extrai corretamente datas com zeros à esquerda."""
        uri = "gs://bucket/tabela/tabela_2024-03-05.csv"
        assert loader._extract_date_from_uri(uri) == "2024-03-05"
