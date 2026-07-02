"""Testes unitários para o entry point da Cloud Function (main.py)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from main import pipeline_handler


class _FakeRequest:
    """Requisição simulada para testes."""

    method = "GET"
    args = {}
    data = b""


@pytest.fixture
def fake_request():
    return _FakeRequest()


class TestPipelineHandler:
    """Testes do handler HTTP pipeline_handler."""

    @patch("main.Orchestrator")
    @patch("main.ConfigManager")
    def test_retorna_200_em_sucesso(self, mock_config_cls, mock_orch_cls, fake_request):
        """Deve retornar 200 com relatório quando pipeline executa com sucesso."""
        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config

        expected_report = {
            "overall_status": "sucesso",
            "tables_processed": ["tabela_a"],
            "tables_failed": [],
        }
        mock_orch = MagicMock()
        mock_orch.run.return_value = expected_report
        mock_orch_cls.return_value = mock_orch

        body, status, headers = pipeline_handler(fake_request)

        assert status == 200
        assert headers["Content-Type"] == "application/json"
        response = json.loads(body)
        assert response["overall_status"] == "sucesso"
        assert response["tables_processed"] == ["tabela_a"]

    @patch("main.ConfigManager")
    def test_retorna_500_em_config_validation_error(self, mock_config_cls, fake_request):
        """Deve retornar 500 com detalhes quando config é inválida."""
        from src.exceptions import ConfigValidationError

        mock_config_cls.side_effect = ConfigValidationError(
            "Campo 'project_id' ausente no config.yaml"
        )

        body, status, headers = pipeline_handler(fake_request)

        assert status == 500
        assert headers["Content-Type"] == "application/json"
        response = json.loads(body)
        assert response["status"] == "erro"
        assert response["etapa"] == "validação_configuração"
        assert "project_id" in response["mensagem"]

    @patch("main.Orchestrator")
    @patch("main.ConfigManager")
    def test_retorna_500_em_erro_inesperado(self, mock_config_cls, mock_orch_cls, fake_request):
        """Deve retornar 500 com mensagem genérica em erro inesperado."""
        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config

        mock_orch = MagicMock()
        mock_orch.run.side_effect = RuntimeError("Falha inesperada")
        mock_orch_cls.return_value = mock_orch

        body, status, headers = pipeline_handler(fake_request)

        assert status == 500
        assert headers["Content-Type"] == "application/json"
        response = json.loads(body)
        assert response["status"] == "erro"
        assert response["etapa"] == "execução_pipeline"
        assert "RuntimeError" in response["mensagem"]
        assert "Falha inesperada" in response["detalhe"]

    @patch("main.Orchestrator")
    @patch("main.ConfigManager")
    def test_chama_config_manager_com_caminho_correto(
        self, mock_config_cls, mock_orch_cls, fake_request
    ):
        """Deve carregar config.yaml do mesmo diretório que main.py."""
        import os

        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config
        mock_orch = MagicMock()
        mock_orch.run.return_value = {"overall_status": "sucesso"}
        mock_orch_cls.return_value = mock_orch

        pipeline_handler(fake_request)

        call_args = mock_config_cls.call_args[0][0]
        assert call_args.endswith("config.yaml")
        assert os.path.isabs(call_args)

    @patch("main.Orchestrator")
    @patch("main.ConfigManager")
    def test_instancia_orchestrator_com_config(
        self, mock_config_cls, mock_orch_cls, fake_request
    ):
        """Deve passar o ConfigManager para o Orchestrator."""
        mock_config = MagicMock()
        mock_config_cls.return_value = mock_config
        mock_orch = MagicMock()
        mock_orch.run.return_value = {"overall_status": "sucesso"}
        mock_orch_cls.return_value = mock_orch

        pipeline_handler(fake_request)

        mock_orch_cls.assert_called_once_with(mock_config)
        mock_orch.run.assert_called_once()
