"""
Modelos de dados e dataclasses de configuração do Pipeline de Dados.

Define as estruturas de dados utilizadas para configuração (YAML),
controle de estado de extração e log de execução.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# ============================================================
# Modelos de Configuração (mapeados a partir do config.yaml)
# ============================================================


@dataclass
class SourceTableConfig:
    """Configuração de uma tabela-fonte para extração via Trino.

    Attributes:
        full_name: Nome completo da tabela no Trino (ex: hive.planejamento.tabela).
            Use "custom_sql" para extrações com SQL customizado.
        short_name: Nome curto da tabela, usado para nomeação de arquivos.
        partition_column: Coluna de particionamento utilizada para extração incremental.
        sql_file: Caminho do arquivo SQL para extrações customizadas (opcional).
        use_max_dt: Se True, usa MAX(dt) ao invés de data atual (opcional).
        group: Grupo de cadência da tabela — "hourly" (gold, incremental rápido)
            ou "daily" (silver, extração completa). Use "all" para sem filtro.
        always_full: Se True, sempre faz extração completa independente do
            estado (necessário para tabelas históricas onde dt não é snapshot
            do dia atual, como re_silver_receita_cb_air).
    """

    full_name: str
    short_name: str
    partition_column: str
    sql_file: Optional[str] = None
    use_max_dt: bool = False
    group: str = "all"
    always_full: bool = False


@dataclass
class DerivedTableConfig:
    """Configuração de uma tabela derivada gerada via SQL no BigQuery.

    Attributes:
        name: Nome identificador da tabela derivada.
        destination: Tabela de destino completa no BigQuery (projeto.dataset.tabela).
        order: Ordem de execução (tabelas com ordem menor executam primeiro).
        sql_file: Caminho do arquivo SQL com a query de transformação.
    """

    name: str
    destination: str
    order: int
    sql_file: str


@dataclass
class SheetsMappingConfig:
    """Mapeamento de uma tabela BigQuery para uma aba de Google Sheets.

    Attributes:
        table: Nome completo da tabela BigQuery de origem.
        spreadsheet_id: ID da planilha Google Sheets de destino.
        sheet_name: Nome da aba de destino dentro da planilha.
    """

    table: str
    spreadsheet_id: str
    sheet_name: str


# ============================================================
# Modelos de Estado e Log (persistidos no BigQuery)
# ============================================================


@dataclass
class ExtractionState:
    """Estado de extração de uma tabela, persistido em pipeline_metadata.extraction_state.

    Attributes:
        table_name: Nome curto da tabela.
        last_extraction_date: Data da última extração bem-sucedida.
        rows_extracted: Quantidade de linhas extraídas na última execução.
        extraction_type: Tipo de extração realizada ('full' ou 'incremental').
        status: Status da última extração ('success' ou 'failed').
        updated_at: Timestamp da última atualização do registro.
    """

    table_name: str
    last_extraction_date: date
    rows_extracted: int
    extraction_type: str  # 'full' ou 'incremental'
    status: str  # 'success' ou 'failed'
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class ExecutionLog:
    """Log de execução de uma etapa do pipeline, persistido em pipeline_metadata.execution_log.

    Attributes:
        execution_id: UUID único da execução.
        started_at: Timestamp de início da execução da etapa.
        finished_at: Timestamp de término da execução (None se ainda em andamento).
        stage: Etapa do pipeline (extração, upload, carga, derivadas, exportação).
        table_name: Nome da tabela sendo processada.
        status: Status da etapa ('sucesso' ou 'falha').
        rows_processed: Quantidade de linhas processadas na etapa.
        error_message: Mensagem de erro, caso tenha ocorrido falha.
    """

    execution_id: str
    started_at: datetime
    finished_at: Optional[datetime]
    stage: str
    table_name: str
    status: str  # 'sucesso' ou 'falha'
    rows_processed: int = 0
    error_message: Optional[str] = None
