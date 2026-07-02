"""Testes unitários para o TrinoExtractor.

Valida detecção de credenciais ausentes/vazias, lógica de retry na conexão,
extração em lotes, tratamento de falha em tabela específica e fechamento
seguro de conexão.

Requirements: 1.3, 1.4, 1.5, 2.4, 2.5
"""

import os
from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest

from src.exceptions import CredentialError
from src.trino_extractor import TrinoExtractor


# ============================================================
# Testes de credenciais ausentes ou vazias
# ============================================================


class TestTrinoExtractorCredenciais:
    """Testes para detecção de credenciais ausentes ou vazias."""

    def test_credential_error_trino_user_ausente(self):
        """CredentialError quando TRINO_USER não está definida."""
        env = {"TRINO_PASSWORD": "senha123"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(CredentialError) as exc_info:
                TrinoExtractor()

            msg = str(exc_info.value)
            assert "TRINO_USER" in msg

    def test_credential_error_trino_password_ausente(self):
        """CredentialError quando TRINO_PASSWORD não está definida."""
        env = {"TRINO_USER": "usuario"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(CredentialError) as exc_info:
                TrinoExtractor()

            msg = str(exc_info.value)
            assert "TRINO_PASSWORD" in msg

    def test_credential_error_ambas_vazias(self):
        """CredentialError quando ambas as variáveis são strings vazias."""
        env = {"TRINO_USER": "", "TRINO_PASSWORD": ""}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(CredentialError) as exc_info:
                TrinoExtractor()

            msg = str(exc_info.value)
            assert "TRINO_USER" in msg
            assert "TRINO_PASSWORD" in msg

    def test_inicializacao_com_credenciais_validas(self):
        """Inicialização bem-sucedida quando credenciais estão presentes."""
        env = {"TRINO_USER": "usuario", "TRINO_PASSWORD": "senha123"}
        with patch.dict(os.environ, env, clear=True):
            extractor = TrinoExtractor()

            assert extractor.username == "usuario"
            assert extractor.password == "senha123"
            assert extractor._connection is None


# ============================================================
# Testes de lógica de retry na conexão
# ============================================================


class TestTrinoExtractorConexao:
    """Testes para lógica de retry na conexão com Trino."""

    @patch("src.trino_extractor.time.sleep")
    @patch("src.trino_extractor.trino_connect")
    def test_connect_falha_3_tentativas_raises_connection_error(
        self, mock_connect, mock_sleep
    ):
        """ConnectionError após 3 tentativas falhadas com sleep de 5s entre elas."""
        mock_connect.side_effect = Exception("Connection refused")

        env = {"TRINO_USER": "user", "TRINO_PASSWORD": "pass"}
        with patch.dict(os.environ, env, clear=True):
            extractor = TrinoExtractor()

            with pytest.raises(ConnectionError) as exc_info:
                extractor.connect()

            msg = str(exc_info.value)
            assert "3 tentativas" in msg

            # Verifica 3 tentativas de conexão
            assert mock_connect.call_count == 3

            # Verifica sleep de 5s entre tentativas (2 sleeps: entre 1ª-2ª e 2ª-3ª)
            assert mock_sleep.call_count == 2
            mock_sleep.assert_called_with(5)

    @patch("src.trino_extractor.time.sleep")
    @patch("src.trino_extractor.trino_connect")
    def test_connect_sucesso_na_segunda_tentativa(self, mock_connect, mock_sleep):
        """Conexão bem-sucedida na segunda tentativa após falha na primeira."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.cursor.return_value = mock_cursor

        # Primeira tentativa falha, segunda tem sucesso
        mock_connect.side_effect = [Exception("Timeout"), mock_conn]

        env = {"TRINO_USER": "user", "TRINO_PASSWORD": "pass"}
        with patch.dict(os.environ, env, clear=True):
            extractor = TrinoExtractor()
            extractor.connect()

            assert extractor._connection == mock_conn
            assert mock_connect.call_count == 2
            # 1 sleep entre primeira e segunda tentativa
            assert mock_sleep.call_count == 1


# ============================================================
# Testes de extração em lotes
# ============================================================


class TestTrinoExtractorExtracao:
    """Testes para extração de dados em lotes (batches)."""

    @patch("src.trino_extractor.trino_connect")
    def test_extract_full_processa_dados_em_batches(self, mock_connect, tmp_path):
        """extract_full() processa dados em lotes via fetchmany até retornar vazio."""
        # Simular dados em 2 batches + 1 batch vazio
        batch_1 = [("a", 1), ("b", 2)]
        batch_2 = [("c", 3)]
        batch_empty = []

        mock_cursor = MagicMock()
        mock_cursor.description = [("col1", None), ("col2", None)]
        mock_cursor.fetchmany.side_effect = [batch_1, batch_2, batch_empty]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        env = {"TRINO_USER": "user", "TRINO_PASSWORD": "pass"}
        with patch.dict(os.environ, env, clear=True):
            extractor = TrinoExtractor()
            extractor._connection = mock_conn

            output_file = str(tmp_path / "output.csv")
            total = extractor.extract_full(
                table="hive.schema.tabela",
                output_path=output_file,
                batch_size=1000,
            )

            assert total == 3
            # Verifica que fetchmany foi chamado com batch_size
            mock_cursor.fetchmany.assert_called_with(1000)
            # Verifica arquivo CSV criado
            with open(output_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # Header + 3 linhas de dados
            assert len(lines) == 4
            assert "col1" in lines[0]

    @patch("src.trino_extractor.trino_connect")
    def test_extract_incremental_filtra_por_data_atual(self, mock_connect, tmp_path):
        """extract_incremental() filtra por dt = data de hoje."""
        batch = [("x", "2024-01-15")]
        batch_empty = []

        mock_cursor = MagicMock()
        mock_cursor.description = [("valor", None), ("dt", None)]
        mock_cursor.fetchmany.side_effect = [batch, batch_empty]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        env = {"TRINO_USER": "user", "TRINO_PASSWORD": "pass"}
        with patch.dict(os.environ, env, clear=True):
            extractor = TrinoExtractor()
            extractor._connection = mock_conn

            output_file = str(tmp_path / "output_inc.csv")
            total = extractor.extract_incremental(
                table="hive.schema.tabela",
                partition_column="dt",
                output_path=output_file,
                batch_size=50000,
            )

            assert total == 1
            # Verifica que a query contém filtro pela data atual
            executed_query = mock_cursor.execute.call_args[0][0]
            data_hoje = date.today().strftime("%Y-%m-%d")
            assert f"dt = '{data_hoje}'" in executed_query

    @patch("src.trino_extractor.trino_connect")
    def test_extract_full_sem_conexao_raises_runtime_error(self, mock_connect):
        """RuntimeError quando extract_full é chamado sem conexão estabelecida."""
        env = {"TRINO_USER": "user", "TRINO_PASSWORD": "pass"}
        with patch.dict(os.environ, env, clear=True):
            extractor = TrinoExtractor()
            # _connection é None (sem connect() prévio)

            with pytest.raises(RuntimeError) as exc_info:
                extractor.extract_full("tabela", "/tmp/out.csv")

            assert "conexão" in str(exc_info.value).lower()


# ============================================================
# Testes de fechamento de conexão
# ============================================================


class TestTrinoExtractorClose:
    """Testes para fechamento seguro de conexão."""

    def test_close_com_conexao_aberta(self):
        """close() fecha conexão e define _connection como None."""
        env = {"TRINO_USER": "user", "TRINO_PASSWORD": "pass"}
        with patch.dict(os.environ, env, clear=True):
            extractor = TrinoExtractor()
            mock_conn = MagicMock()
            extractor._connection = mock_conn

            extractor.close()

            mock_conn.close.assert_called_once()
            assert extractor._connection is None

    def test_close_sem_conexao_nao_levanta_erro(self):
        """close() é seguro quando _connection é None."""
        env = {"TRINO_USER": "user", "TRINO_PASSWORD": "pass"}
        with patch.dict(os.environ, env, clear=True):
            extractor = TrinoExtractor()
            assert extractor._connection is None

            # Não deve levantar exceção
            extractor.close()
            assert extractor._connection is None

    def test_close_com_excecao_no_fechamento(self):
        """close() não propaga exceção se conn.close() falhar."""
        env = {"TRINO_USER": "user", "TRINO_PASSWORD": "pass"}
        with patch.dict(os.environ, env, clear=True):
            extractor = TrinoExtractor()
            mock_conn = MagicMock()
            mock_conn.close.side_effect = Exception("Erro inesperado")
            extractor._connection = mock_conn

            # Não deve levantar exceção
            extractor.close()
            assert extractor._connection is None
