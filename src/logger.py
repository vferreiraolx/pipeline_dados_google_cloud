"""
Logger estruturado do Pipeline de Dados.

Fornece logging em formato estruturado em português para todas as etapas
do pipeline, permitindo rastreabilidade e diagnóstico de problemas.

Formato: [{timestamp}] [{etapa}] [{status}] Tabela: {nome_tabela} | Registros: {contagem} | {mensagem}
"""

import logging
from datetime import datetime
from typing import Optional


# Etapas válidas do pipeline
ETAPAS_VALIDAS = (
    "EXTRAÇÃO",
    "UPLOAD_GCS",
    "CARGA_BQ",
    "TABELA_DERIVADA",
    "EXPORTAÇÃO_SHEETS",
    "CONFIGURAÇÃO",
    "CONEXÃO",
)

# Status válidos
STATUS_VALIDOS = (
    "SUCESSO",
    "FALHA",
    "INICIO",
    "AVISO",
)


class PipelineFormatter(logging.Formatter):
    """Formatter customizado que formata logs no padrão estruturado do pipeline.

    Formato:
        [{timestamp}] [{etapa}] [{status}] Tabela: {nome_tabela} | Registros: {contagem} | {mensagem}

    Exemplo:
        [2024-01-15T10:00:05] [EXTRAÇÃO] [SUCESSO] Tabela: re_gold_receita_unificado_air | Registros: 45230 | Extração incremental concluída
    """

    def format(self, record: logging.LogRecord) -> str:
        """Formata o registro de log no padrão estruturado.

        Se o registro possuir os atributos extras (etapa, status, nome_tabela,
        contagem), utiliza o formato estruturado. Caso contrário, utiliza
        formato padrão com timestamp e mensagem.
        """
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%S")

        etapa = getattr(record, "etapa", None)
        status = getattr(record, "status", None)
        nome_tabela = getattr(record, "nome_tabela", "N/A")
        contagem = getattr(record, "contagem", 0)

        if etapa and status:
            return (
                f"[{timestamp}] [{etapa}] [{status}] "
                f"Tabela: {nome_tabela} | Registros: {contagem} | {record.getMessage()}"
            )

        # Formato fallback para logs sem metadados de pipeline
        return f"[{timestamp}] {record.getMessage()}"


def setup_logger(name: str = "pipeline", level: int = logging.INFO) -> logging.Logger:
    """Configura e retorna um logger com o formatter estruturado do pipeline.

    Args:
        name: Nome do logger. Padrão: 'pipeline'.
        level: Nível de logging. Padrão: logging.INFO.

    Returns:
        Logger configurado com o PipelineFormatter.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Evita adicionar handlers duplicados
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        handler.setFormatter(PipelineFormatter())
        logger.addHandler(handler)

    return logger


def log_step(
    etapa: str,
    status: str,
    nome_tabela: str,
    contagem: int,
    mensagem: str,
    logger: Optional[logging.Logger] = None,
) -> None:
    """Registra um log estruturado para uma etapa do pipeline.

    Args:
        etapa: Nome da etapa do pipeline (ex: EXTRAÇÃO, UPLOAD_GCS, CARGA_BQ).
        status: Status da operação (SUCESSO, FALHA, INICIO, AVISO).
        nome_tabela: Nome da tabela sendo processada.
        contagem: Quantidade de registros processados.
        mensagem: Descrição da operação ou do erro.
        logger: Logger a ser utilizado. Se None, usa o logger padrão 'pipeline'.

    Exemplo:
        >>> log_step("EXTRAÇÃO", "SUCESSO", "re_gold_receita_unificado_air", 45230, "Extração incremental concluída")
        [2024-01-15T10:00:05] [EXTRAÇÃO] [SUCESSO] Tabela: re_gold_receita_unificado_air | Registros: 45230 | Extração incremental concluída
    """
    if logger is None:
        logger = setup_logger()

    extra = {
        "etapa": etapa,
        "status": status,
        "nome_tabela": nome_tabela,
        "contagem": contagem,
    }

    # Determina o nível de log com base no status
    if status == "FALHA":
        logger.error(mensagem, extra=extra)
    elif status == "AVISO":
        logger.warning(mensagem, extra=extra)
    else:
        logger.info(mensagem, extra=extra)
