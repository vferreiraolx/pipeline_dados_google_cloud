"""Testes unitários para o GCSUploader.

Valida construção de paths no GCS, lógica de retry com 3 tentativas,
remoção de arquivo local em sucesso e manutenção do arquivo em falha.
"""

import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.gcs_uploader import GCSUploader


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_storage_client():
    """Mock do google.cloud.storage.Client e Bucket."""
    with patch("src.gcs_uploader.storage.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_client_cls.return_value = mock_client

        yield {
            "client_cls": mock_client_cls,
            "client": mock_client,
            "bucket": mock_bucket,
        }


@pytest.fixture
def uploader(mock_storage_client):
    """Instância de GCSUploader com mocks configurados."""
    return GCSUploader(
        project="conect-python-g-sheets",
        bucket_name="teste-extracao-trino",
    )


@pytest.fixture
def local_csv(tmp_path):
    """Cria arquivo CSV local temporário para testes de upload."""
    csv_file = tmp_path / "dados.csv"
    csv_file.write_text("col1,col2\nval1,val2\n")
    return str(csv_file)


# ============================================================
# Testes de inicialização
# ============================================================


class TestGCSUploaderInit:
    """Testes de inicialização do GCSUploader."""

    def test_inicializa_com_projeto_e_bucket_padrao(self, mock_storage_client):
        """GCSUploader inicializa com projeto e bucket padrão."""
        uploader = GCSUploader()
        assert uploader.project == "conect-python-g-sheets"
        assert uploader.bucket_name == "teste-extracao-trino"

    def test_inicializa_com_projeto_e_bucket_custom(self, mock_storage_client):
        """GCSUploader aceita projeto e bucket customizados."""
        uploader = GCSUploader(project="meu-projeto", bucket_name="meu-bucket")
        assert uploader.project == "meu-projeto"
        assert uploader.bucket_name == "meu-bucket"

    def test_cria_cliente_com_adc(self, mock_storage_client):
        """Cliente GCS é criado com o projeto especificado (ADC)."""
        GCSUploader(project="conect-python-g-sheets")
        mock_storage_client["client_cls"].assert_called_once_with(
            project="conect-python-g-sheets"
        )

    def test_obtem_bucket_pelo_nome(self, mock_storage_client):
        """Bucket é obtido pelo nome do bucket informado."""
        GCSUploader(bucket_name="teste-extracao-trino")
        mock_storage_client["client"].bucket.assert_called_once_with(
            "teste-extracao-trino"
        )


# ============================================================
# Testes de build_gcs_path
# ============================================================


class TestBuildGcsPath:
    """Testes para geração do caminho GCS."""

    def test_gera_path_com_data_fornecida(self, uploader):
        """Path segue padrão {table_name}/{table_name}_{YYYY-MM-DD}.csv."""
        result = uploader.build_gcs_path(
            table_name="re_gold_receita_unificado_air",
            extraction_date=date(2024, 1, 15),
        )
        expected = "re_gold_receita_unificado_air/re_gold_receita_unificado_air_2024-01-15.csv"
        assert result == expected

    def test_gera_path_com_data_atual_quando_nao_fornecida(self, uploader):
        """Path usa data atual quando extraction_date é None."""
        today = date.today()
        date_str = today.strftime("%Y-%m-%d")

        result = uploader.build_gcs_path(table_name="minha_tabela")
        expected = f"minha_tabela/minha_tabela_{date_str}.csv"
        assert result == expected

    def test_gera_path_formato_correto_dia_mes_com_zero(self, uploader):
        """Path formata corretamente meses e dias com zero à esquerda."""
        result = uploader.build_gcs_path(
            table_name="tabela_teste",
            extraction_date=date(2024, 3, 5),
        )
        assert result == "tabela_teste/tabela_teste_2024-03-05.csv"


# ============================================================
# Testes de upload com sucesso
# ============================================================


class TestUploadSucesso:
    """Testes para upload bem-sucedido."""

    def test_upload_sucesso_chama_upload_from_filename(
        self, uploader, mock_storage_client, local_csv
    ):
        """Upload chama blob.upload_from_filename com caminho local."""
        mock_blob = MagicMock()
        mock_storage_client["bucket"].blob.return_value = mock_blob

        uploader.upload(local_csv, "tabela/tabela_2024-01-15.csv")

        mock_storage_client["bucket"].blob.assert_called_once_with(
            "tabela/tabela_2024-01-15.csv"
        )
        mock_blob.upload_from_filename.assert_called_once_with(local_csv)

    def test_upload_sucesso_remove_arquivo_local(
        self, uploader, mock_storage_client, local_csv
    ):
        """Arquivo local é removido após upload com sucesso."""
        mock_blob = MagicMock()
        mock_storage_client["bucket"].blob.return_value = mock_blob

        assert os.path.exists(local_csv)
        uploader.upload(local_csv, "tabela/tabela_2024-01-15.csv")
        assert not os.path.exists(local_csv)

    def test_upload_sobrescreve_arquivo_existente(
        self, uploader, mock_storage_client, local_csv
    ):
        """Upload sobrescreve arquivo no GCS (comportamento padrão do blob)."""
        mock_blob = MagicMock()
        mock_storage_client["bucket"].blob.return_value = mock_blob

        uploader.upload(local_csv, "tabela/tabela_2024-01-15.csv")

        # blob.upload_from_filename sobrescreve por padrão
        mock_blob.upload_from_filename.assert_called_once()


# ============================================================
# Testes de upload com retry
# ============================================================


class TestUploadRetry:
    """Testes para lógica de retry do upload."""

    @patch("src.gcs_uploader.time.sleep")
    def test_retry_3_tentativas_com_intervalo_30s(
        self, mock_sleep, uploader, mock_storage_client, local_csv
    ):
        """Upload realiza 3 tentativas com intervalo de 30s entre elas."""
        mock_blob = MagicMock()
        mock_blob.upload_from_filename.side_effect = Exception("Erro de rede")
        mock_storage_client["bucket"].blob.return_value = mock_blob

        uploader.upload(local_csv, "tabela/tabela_2024-01-15.csv")

        assert mock_blob.upload_from_filename.call_count == 3
        # sleep é chamado entre tentativas (2 vezes: entre 1-2 e entre 2-3)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(30)

    @patch("src.gcs_uploader.time.sleep")
    def test_retry_sucesso_na_segunda_tentativa(
        self, mock_sleep, uploader, mock_storage_client, local_csv
    ):
        """Upload com sucesso na segunda tentativa remove arquivo local."""
        mock_blob = MagicMock()
        mock_blob.upload_from_filename.side_effect = [
            Exception("Falha temporária"),
            None,  # Sucesso na segunda tentativa
        ]
        mock_storage_client["bucket"].blob.return_value = mock_blob

        assert os.path.exists(local_csv)
        uploader.upload(local_csv, "tabela/tabela_2024-01-15.csv")

        assert mock_blob.upload_from_filename.call_count == 2
        assert not os.path.exists(local_csv)


# ============================================================
# Testes de upload com falha total
# ============================================================


class TestUploadFalha:
    """Testes para falha total do upload após todas as tentativas."""

    @patch("src.gcs_uploader.time.sleep")
    def test_falha_total_mantem_arquivo_local(
        self, mock_sleep, uploader, mock_storage_client, local_csv
    ):
        """Arquivo local é mantido quando upload falha após 3 tentativas."""
        mock_blob = MagicMock()
        mock_blob.upload_from_filename.side_effect = Exception("Erro persistente")
        mock_storage_client["bucket"].blob.return_value = mock_blob

        uploader.upload(local_csv, "tabela/tabela_2024-01-15.csv")

        assert os.path.exists(local_csv)

    @patch("src.gcs_uploader.time.sleep")
    def test_falha_total_nao_lanca_excecao(
        self, mock_sleep, uploader, mock_storage_client, local_csv
    ):
        """Upload que falha não propaga exceção (registra via log)."""
        mock_blob = MagicMock()
        mock_blob.upload_from_filename.side_effect = Exception("Erro de conexão")
        mock_storage_client["bucket"].blob.return_value = mock_blob

        # Não deve lançar exceção
        uploader.upload(local_csv, "tabela/tabela_2024-01-15.csv")
