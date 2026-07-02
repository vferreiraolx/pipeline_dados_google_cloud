"""
Gerenciador de configuração do Pipeline de Dados.

Carrega, valida e fornece acesso à configuração YAML do pipeline.
Todas as mensagens de erro são em português para facilitar a operação
pelo time de Planejamento Comercial.
"""

import os
from pathlib import Path

import yaml

from src.exceptions import ConfigValidationError
from src.models import DerivedTableConfig, SheetsMappingConfig, SourceTableConfig


class ConfigManager:
    """Carrega e valida o arquivo config.yaml do pipeline.

    Responsável por:
    - Carregar e fazer parsing do YAML
    - Validar sintaxe, campos obrigatórios e referências
    - Fornecer acesso tipado às configurações via dataclasses

    Raises:
        ConfigValidationError: Se o arquivo contiver erros de sintaxe,
            campos ausentes ou referências inválidas.
    """

    # Chaves obrigatórias no nível raiz do config.yaml
    REQUIRED_TOP_LEVEL_KEYS = [
        "project_id",
        "bucket_name",
        "trino",
        "extraction",
        "gcs",
        "bigquery",
        "derived_tables",
        "sheets_export",
    ]

    # Campos obrigatórios para cada tabela de extração
    REQUIRED_TABLE_FIELDS = ["full_name", "short_name"]

    # Campos obrigatórios para cada tabela derivada
    REQUIRED_DERIVED_TABLE_FIELDS = ["name", "destination", "order", "sql_file"]

    # Campos obrigatórios para cada mapeamento de exportação Sheets
    REQUIRED_SHEETS_MAPPING_FIELDS = ["table", "spreadsheet_id", "sheet_name"]

    def __init__(self, config_path: str):
        """Carrega e valida configuração YAML.

        Args:
            config_path: Caminho para o arquivo config.yaml.

        Raises:
            ConfigValidationError: Se o arquivo não existir, tiver
                sintaxe inválida ou falhar na validação.
        """
        self._config_path = config_path
        self._base_dir = str(Path(config_path).parent)
        self._config: dict = {}

        self._load()
        self._validate()

    def _load(self) -> None:
        """Carrega e faz parsing do arquivo YAML.

        Raises:
            ConfigValidationError: Se o arquivo não existir ou tiver
                sintaxe YAML inválida.
        """
        if not os.path.isfile(self._config_path):
            raise ConfigValidationError(
                f"Arquivo de configuração não encontrado: '{self._config_path}'. "
                f"Verifique se o caminho está correto e o arquivo existe."
            )

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigValidationError(
                f"Erro de sintaxe YAML no arquivo '{self._config_path}': {e}. "
                f"Corrija a formatação do arquivo YAML."
            )

        if content is None:
            raise ConfigValidationError(
                f"Arquivo de configuração '{self._config_path}' está vazio. "
                f"Adicione as configurações necessárias do pipeline."
            )

        if not isinstance(content, dict):
            raise ConfigValidationError(
                f"Arquivo de configuração '{self._config_path}' deve conter "
                f"um mapeamento YAML no nível raiz (chave: valor)."
            )

        self._config = content

    def _validate(self) -> None:
        """Executa todas as validações no config carregado.

        Raises:
            ConfigValidationError: Se qualquer validação falhar.
        """
        self._validate_top_level_keys()
        self._validate_extraction_tables()
        self._validate_derived_tables()
        self._validate_sheets_mappings()

    def _validate_top_level_keys(self) -> None:
        """Valida que todas as chaves obrigatórias existem no nível raiz."""
        missing_keys = [
            key for key in self.REQUIRED_TOP_LEVEL_KEYS if key not in self._config
        ]
        if missing_keys:
            keys_str = ", ".join(f"'{k}'" for k in missing_keys)
            raise ConfigValidationError(
                f"Arquivo '{self._config_path}': campos obrigatórios ausentes "
                f"no nível raiz: {keys_str}. "
                f"Adicione esses campos ao arquivo de configuração."
            )

    def _validate_extraction_tables(self) -> None:
        """Valida a seção 'extraction.tables' do config."""
        extraction = self._config.get("extraction", {})

        if not isinstance(extraction, dict):
            raise ConfigValidationError(
                f"Arquivo '{self._config_path}': o campo 'extraction' deve ser "
                f"um mapeamento contendo 'tables'. "
                f"Corrija a estrutura da seção 'extraction'."
            )

        tables = extraction.get("tables")

        if tables is None:
            raise ConfigValidationError(
                f"Arquivo '{self._config_path}': campo 'extraction.tables' "
                f"ausente. Adicione a lista de tabelas a serem extraídas."
            )

        if not isinstance(tables, list):
            raise ConfigValidationError(
                f"Arquivo '{self._config_path}': campo 'extraction.tables' "
                f"deve ser uma lista de tabelas. "
                f"Corrija para usar o formato de lista YAML (itens com '- ')."
            )

        if len(tables) == 0:
            raise ConfigValidationError(
                f"Arquivo '{self._config_path}': campo 'extraction.tables' "
                f"está vazio. Adicione pelo menos uma tabela para extração."
            )

        for i, table in enumerate(tables):
            if not isinstance(table, dict):
                raise ConfigValidationError(
                    f"Arquivo '{self._config_path}': tabela na posição {i + 1} "
                    f"em 'extraction.tables' deve ser um mapeamento com os "
                    f"campos: {', '.join(self.REQUIRED_TABLE_FIELDS)}."
                )

            missing_fields = [
                field
                for field in self.REQUIRED_TABLE_FIELDS
                if field not in table
            ]
            if missing_fields:
                table_name = table.get("full_name", table.get("short_name", f"posição {i + 1}"))
                fields_str = ", ".join(f"'{f}'" for f in missing_fields)
                raise ConfigValidationError(
                    f"Arquivo '{self._config_path}': tabela '{table_name}' em "
                    f"'extraction.tables' está com campos obrigatórios ausentes: "
                    f"{fields_str}. Adicione esses campos à configuração da tabela."
                )

    def _validate_derived_tables(self) -> None:
        """Valida a seção 'derived_tables' do config."""
        derived_tables = self._config.get("derived_tables")

        if not isinstance(derived_tables, list):
            raise ConfigValidationError(
                f"Arquivo '{self._config_path}': campo 'derived_tables' "
                f"deve ser uma lista de tabelas derivadas. "
                f"Corrija para usar o formato de lista YAML (itens com '- ')."
            )

        for i, table in enumerate(derived_tables):
            if not isinstance(table, dict):
                raise ConfigValidationError(
                    f"Arquivo '{self._config_path}': tabela derivada na posição "
                    f"{i + 1} em 'derived_tables' deve ser um mapeamento com os "
                    f"campos: {', '.join(self.REQUIRED_DERIVED_TABLE_FIELDS)}."
                )

            missing_fields = [
                field
                for field in self.REQUIRED_DERIVED_TABLE_FIELDS
                if field not in table
            ]
            if missing_fields:
                table_name = table.get("name", f"posição {i + 1}")
                fields_str = ", ".join(f"'{f}'" for f in missing_fields)
                raise ConfigValidationError(
                    f"Arquivo '{self._config_path}': tabela derivada "
                    f"'{table_name}' está com campos obrigatórios ausentes: "
                    f"{fields_str}. Adicione esses campos à configuração."
                )

            # Validar que o arquivo SQL referenciado existe
            sql_file = table.get("sql_file", "")
            sql_path = os.path.join(self._base_dir, sql_file)
            if not os.path.isfile(sql_path):
                table_name = table.get("name", f"posição {i + 1}")
                raise ConfigValidationError(
                    f"Arquivo '{self._config_path}': tabela derivada "
                    f"'{table_name}' referencia o arquivo SQL "
                    f"'{sql_file}' que não foi encontrado em "
                    f"'{sql_path}'. Crie o arquivo SQL ou corrija o caminho."
                )

    def _validate_sheets_mappings(self) -> None:
        """Valida a seção 'sheets_export.mappings' do config."""
        sheets_export = self._config.get("sheets_export")

        if not isinstance(sheets_export, dict):
            raise ConfigValidationError(
                f"Arquivo '{self._config_path}': campo 'sheets_export' "
                f"deve ser um mapeamento contendo 'mappings'. "
                f"Corrija a estrutura da seção 'sheets_export'."
            )

        mappings = sheets_export.get("mappings")

        if mappings is None:
            raise ConfigValidationError(
                f"Arquivo '{self._config_path}': campo "
                f"'sheets_export.mappings' ausente. "
                f"Adicione a lista de mapeamentos de exportação para Sheets."
            )

        if not isinstance(mappings, list):
            raise ConfigValidationError(
                f"Arquivo '{self._config_path}': campo "
                f"'sheets_export.mappings' deve ser uma lista. "
                f"Corrija para usar o formato de lista YAML (itens com '- ')."
            )

        for i, mapping in enumerate(mappings):
            if not isinstance(mapping, dict):
                raise ConfigValidationError(
                    f"Arquivo '{self._config_path}': mapeamento na posição "
                    f"{i + 1} em 'sheets_export.mappings' deve ser um "
                    f"mapeamento com os campos: "
                    f"{', '.join(self.REQUIRED_SHEETS_MAPPING_FIELDS)}."
                )

            missing_fields = [
                field
                for field in self.REQUIRED_SHEETS_MAPPING_FIELDS
                if field not in mapping
            ]
            if missing_fields:
                table_ref = mapping.get("table", f"posição {i + 1}")
                fields_str = ", ".join(f"'{f}'" for f in missing_fields)
                raise ConfigValidationError(
                    f"Arquivo '{self._config_path}': mapeamento Sheets "
                    f"'{table_ref}' está com campos obrigatórios ausentes: "
                    f"{fields_str}. Adicione esses campos ao mapeamento."
                )

    def get_source_tables(self, group: str = "all") -> list[SourceTableConfig]:
        """Retorna lista de tabelas-fonte configuradas, filtradas por grupo de cadência.

        Args:
            group: Grupo de cadência para filtrar — "hourly", "daily" ou "all".
                "all" retorna todas as tabelas (comportamento padrão/legado).

        Returns:
            Lista de SourceTableConfig com as tabelas para extração.
        """
        tables = self._config["extraction"]["tables"]
        configs = [
            SourceTableConfig(
                full_name=t["full_name"],
                short_name=t["short_name"],
                partition_column=t.get("partition_column", ""),
                sql_file=t.get("sql_file"),
                use_max_dt=t.get("use_max_dt", False),
                group=t.get("group", "all"),
                always_full=t.get("always_full", False),
            )
            for t in tables
        ]
        if group == "all":
            return configs
        return [t for t in configs if t.group == group]

    def get_derived_tables(self) -> list[DerivedTableConfig]:
        """Retorna tabelas derivadas ordenadas por ordem de execução.

        Returns:
            Lista de DerivedTableConfig ordenada pelo campo 'order'.
        """
        derived = self._config["derived_tables"]
        sorted_tables = sorted(derived, key=lambda t: t["order"])
        return [
            DerivedTableConfig(
                name=t["name"],
                destination=t["destination"],
                order=t["order"],
                sql_file=t["sql_file"],
            )
            for t in sorted_tables
        ]

    def get_sheets_mappings(self) -> list[SheetsMappingConfig]:
        """Retorna mapeamentos tabela BigQuery -> Google Sheets.

        Returns:
            Lista de SheetsMappingConfig com os mapeamentos de exportação.
        """
        mappings = self._config["sheets_export"]["mappings"]
        return [
            SheetsMappingConfig(
                table=m["table"],
                spreadsheet_id=m["spreadsheet_id"],
                sheet_name=m["sheet_name"],
            )
            for m in mappings
        ]

    @property
    def project_id(self) -> str:
        """Retorna o ID do projeto GCP."""
        return self._config["project_id"]

    @property
    def bucket_name(self) -> str:
        """Retorna o nome do bucket GCS."""
        return self._config["bucket_name"]

    @property
    def config(self) -> dict:
        """Retorna o dicionário completo de configuração."""
        return self._config
