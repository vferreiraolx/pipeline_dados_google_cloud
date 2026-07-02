"""Testes unitários para o ConfigManager.

Valida carregamento de configuração válida, detecção de erros de sintaxe YAML,
campos obrigatórios ausentes, referências SQL inválidas e arquivo vazio.
Todas as mensagens de erro devem ser em português.
"""

import pytest
import yaml

from src.config_manager import ConfigManager
from src.exceptions import ConfigValidationError
from src.models import DerivedTableConfig, SheetsMappingConfig, SourceTableConfig


# ============================================================
# Fixtures
# ============================================================


VALID_CONFIG = {
    "project_id": "conect-python-g-sheets",
    "bucket_name": "teste-extracao-trino",
    "trino": {
        "host": "trino-gateway.dataeng.bigdata.olxbr.io",
        "port": 443,
        "protocol": "https",
    },
    "extraction": {
        "batch_size": 100000,
        "tables": [
            {
                "full_name": "hive.planejamento.re_gold_receita_unificado_air",
                "short_name": "re_gold_receita_unificado_air",
                "partition_column": "dt",
            },
        ],
    },
    "gcs": {"retry_attempts": 3, "retry_interval_seconds": 30},
    "bigquery": {"dataset": "planejamento_comercial"},
    "derived_tables": [
        {
            "name": "receita_consolidada",
            "destination": "conect-python-g-sheets.planejamento_comercial.receita_consolidada",
            "order": 1,
            "sql_file": "sql/receita_consolidada.sql",
        },
    ],
    "sheets_export": {
        "retry_attempts": 3,
        "mappings": [
            {
                "table": "conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air",
                "spreadsheet_id": "1ABC",
                "sheet_name": "Receita Unificado",
            },
        ],
    },
}


@pytest.fixture
def valid_config_file(tmp_path):
    """Cria arquivo config.yaml válido com SQL existente no filesystem."""
    config_path = tmp_path / "config.yaml"

    # Criar arquivo SQL referenciado
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    sql_file = sql_dir / "receita_consolidada.sql"
    sql_file.write_text("SELECT * FROM tabela;")

    config_path.write_text(yaml.dump(VALID_CONFIG, allow_unicode=True))
    return str(config_path)


# ============================================================
# Testes de carregamento de config válida
# ============================================================


class TestConfigManagerValida:
    """Testes para carregamento de configuração válida."""

    def test_carregamento_config_valida(self, valid_config_file):
        """Config válida carrega sem erros e retorna instância."""
        cm = ConfigManager(valid_config_file)
        assert cm.project_id == "conect-python-g-sheets"
        assert cm.bucket_name == "teste-extracao-trino"

    def test_get_source_tables_retorna_dataclasses(self, valid_config_file):
        """get_source_tables retorna lista de SourceTableConfig."""
        cm = ConfigManager(valid_config_file)
        tables = cm.get_source_tables()

        assert len(tables) == 1
        assert isinstance(tables[0], SourceTableConfig)
        assert tables[0].full_name == "hive.planejamento.re_gold_receita_unificado_air"
        assert tables[0].short_name == "re_gold_receita_unificado_air"
        assert tables[0].partition_column == "dt"

    def test_get_derived_tables_retorna_dataclasses(self, valid_config_file):
        """get_derived_tables retorna lista de DerivedTableConfig."""
        cm = ConfigManager(valid_config_file)
        tables = cm.get_derived_tables()

        assert len(tables) == 1
        assert isinstance(tables[0], DerivedTableConfig)
        assert tables[0].name == "receita_consolidada"
        assert tables[0].order == 1
        assert tables[0].sql_file == "sql/receita_consolidada.sql"

    def test_get_sheets_mappings_retorna_dataclasses(self, valid_config_file):
        """get_sheets_mappings retorna lista de SheetsMappingConfig."""
        cm = ConfigManager(valid_config_file)
        mappings = cm.get_sheets_mappings()

        assert len(mappings) == 1
        assert isinstance(mappings[0], SheetsMappingConfig)
        assert mappings[0].sheet_name == "Receita Unificado"
        assert mappings[0].spreadsheet_id == "1ABC"


# ============================================================
# Testes de validação com campos obrigatórios faltando
# ============================================================


class TestConfigManagerCamposFaltando:
    """Testes para validação de campos obrigatórios ausentes."""

    def test_campo_top_level_faltando(self, tmp_path):
        """Erro em português quando campo obrigatório do nível raiz está ausente."""
        config = VALID_CONFIG.copy()
        del config["project_id"]

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config, allow_unicode=True))

        # Criar SQL para não falhar na validação de derived_tables
        sql_dir = tmp_path / "sql"
        sql_dir.mkdir()
        (sql_dir / "receita_consolidada.sql").write_text("SELECT 1;")

        with pytest.raises(ConfigValidationError) as exc_info:
            ConfigManager(str(config_path))

        msg = str(exc_info.value)
        assert "obrigatórios ausentes" in msg.lower() or "obrigatórios ausentes" in msg
        assert "project_id" in msg

    def test_campo_tabela_extracao_faltando(self, tmp_path):
        """Erro em português quando campo de tabela de extração está ausente."""
        config = VALID_CONFIG.copy()
        config = {**config}
        config["extraction"] = {
            "batch_size": 100000,
            "tables": [
                {
                    "full_name": "hive.planejamento.tabela_teste",
                    # short_name ausente
                    "partition_column": "dt",
                },
            ],
        }

        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config, allow_unicode=True))

        sql_dir = tmp_path / "sql"
        sql_dir.mkdir()
        (sql_dir / "receita_consolidada.sql").write_text("SELECT 1;")

        with pytest.raises(ConfigValidationError) as exc_info:
            ConfigManager(str(config_path))

        msg = str(exc_info.value)
        assert "short_name" in msg
        assert "obrigatórios ausentes" in msg.lower() or "campos obrigatórios" in msg.lower()


# ============================================================
# Testes de validação com referência SQL inválida
# ============================================================


class TestConfigManagerReferenciaSQL:
    """Testes para validação de referência a arquivo SQL inexistente."""

    def test_sql_file_nao_encontrado(self, tmp_path):
        """Erro em português quando arquivo SQL referenciado não existe."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(VALID_CONFIG, allow_unicode=True))

        # Não criar o arquivo SQL referenciado

        with pytest.raises(ConfigValidationError) as exc_info:
            ConfigManager(str(config_path))

        msg = str(exc_info.value)
        assert "sql" in msg.lower()
        assert "não foi encontrado" in msg.lower() or "não encontrado" in msg.lower()


# ============================================================
# Testes de validação com sintaxe YAML inválida
# ============================================================


class TestConfigManagerSintaxeYAML:
    """Testes para detecção de erros de sintaxe YAML."""

    def test_yaml_invalido(self, tmp_path):
        """Erro em português quando config contém YAML com sintaxe inválida."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("project_id: [\ninvalid: yaml: content:\n  - broken")

        with pytest.raises(ConfigValidationError) as exc_info:
            ConfigManager(str(config_path))

        msg = str(exc_info.value)
        assert "sintaxe yaml" in msg.lower() or "erro de sintaxe" in msg.lower()


# ============================================================
# Testes de validação com arquivo vazio
# ============================================================


class TestConfigManagerArquivoVazio:
    """Testes para detecção de arquivo de configuração vazio."""

    def test_config_vazio(self, tmp_path):
        """Erro em português quando config está vazio."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("")

        with pytest.raises(ConfigValidationError) as exc_info:
            ConfigManager(str(config_path))

        msg = str(exc_info.value)
        assert "vazio" in msg.lower()


# ============================================================
# Testes de arquivo inexistente
# ============================================================


class TestConfigManagerArquivoInexistente:
    """Testes para detecção de arquivo de configuração inexistente."""

    def test_arquivo_nao_encontrado(self, tmp_path):
        """Erro em português quando arquivo de configuração não existe."""
        config_path = tmp_path / "config_inexistente.yaml"

        with pytest.raises(ConfigValidationError) as exc_info:
            ConfigManager(str(config_path))

        msg = str(exc_info.value)
        assert "não encontrado" in msg.lower()
