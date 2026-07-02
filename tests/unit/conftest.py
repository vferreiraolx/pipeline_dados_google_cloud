"""Configuração compartilhada para testes unitários."""

import pytest


@pytest.fixture
def sample_config_path(tmp_path):
    """Retorna caminho para um arquivo de configuração temporário."""
    return tmp_path / "config.yaml"
