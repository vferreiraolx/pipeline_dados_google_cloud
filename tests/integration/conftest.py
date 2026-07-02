"""Configuração compartilhada para testes de integração."""

import pytest


def pytest_addoption(parser):
    """Adiciona opção --run-integration para executar testes de integração."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Executar testes de integração (requer credenciais configuradas)",
    )


def pytest_collection_modifyitems(config, items):
    """Pula testes de integração se --run-integration não for passado."""
    if not config.getoption("--run-integration"):
        skip_integration = pytest.mark.skip(
            reason="Requer --run-integration para executar"
        )
        for item in items:
            item.add_marker(skip_integration)
