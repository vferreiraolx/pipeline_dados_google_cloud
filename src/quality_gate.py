"""Quality Gate pré-trigger Tableau.

Valida que os dados no BigQuery são confiáveis antes de acionar o refresh
do Tableau Cloud. Se o gate falhar, o trigger é suprimido — evitando que o
Tableau exiba dados inválidos (zeros, tabelas vazias, dados muito antigos).

Checks executados:
    1. gold_row_count    — re_gold_receita_unificado_air tem linhas (> 0)
    2. gold_freshness    — max(dt) >= hoje - 1 (dado de ontem no mínimo)
    3. consolidada_count — receita_consolidada tem linhas (> 0)

Cada check é independente: falha em um não impede os demais de rodar.
Módulo sem dependências externas além de google-cloud-bigquery (já no requirements).
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT = "conect-python-g-sheets"
DATASET = "planejamento_comercial"
GOLD_TABLE = f"{PROJECT}.{DATASET}.re_gold_receita_unificado_air"
CONSOLIDADA_TABLE = f"{PROJECT}.{DATASET}.receita_consolidada"


@dataclass
class CheckResult:
    """Resultado de um check individual do quality gate."""

    passed: bool
    message: str


@dataclass
class QualityGateResult:
    """Resultado agregado do quality gate.

    Attributes:
        passed: True somente quando TODOS os checks passaram.
        failures: Lista de mensagens de falha (vazia quando passed=True).
    """

    passed: bool
    failures: List[str] = field(default_factory=list)


def _check_gold_row_count(client: bigquery.Client) -> CheckResult:
    """Verifica que a tabela gold tem pelo menos 1 linha."""
    try:
        result = client.query(
            f"SELECT COUNT(*) AS n FROM `{GOLD_TABLE}`"
        ).result()
        n = next(iter(result)).n
        if n > 0:
            return CheckResult(passed=True, message=f"gold_row_count: {n}")
        return CheckResult(passed=False, message=f"gold_row_count: 0 — tabela vazia")
    except Exception as e:
        return CheckResult(passed=False, message=f"gold_row_count: erro na query — {e}")


def _check_gold_freshness(client: bigquery.Client) -> CheckResult:
    """Verifica que max(dt) >= hoje - 1 (dado de ontem no mínimo).

    Tolerância de 1 dia: o pipeline horário do gold roda ao longo do dia,
    então às 00h ainda não teremos o dado de hoje — mas devemos ter de ontem.
    """
    try:
        result = client.query(
            f"SELECT MAX(dt) AS max_dt FROM `{GOLD_TABLE}`"
        ).result()
        max_dt = next(iter(result)).max_dt
        if max_dt is None:
            return CheckResult(passed=False, message="gold_freshness: max(dt) é NULL")

        threshold = date.today() - timedelta(days=1)
        if max_dt >= threshold:
            return CheckResult(
                passed=True, message=f"gold_freshness: max(dt)={max_dt} OK"
            )
        stale_days = (date.today() - max_dt).days
        return CheckResult(
            passed=False,
            message=f"gold_freshness: max(dt)={max_dt} está {stale_days} dia(s) atrasado",
        )
    except Exception as e:
        return CheckResult(passed=False, message=f"gold_freshness: erro na query — {e}")


def _check_consolidada_row_count(client: bigquery.Client) -> CheckResult:
    """Verifica que receita_consolidada tem pelo menos 1 linha."""
    try:
        result = client.query(
            f"SELECT COUNT(*) AS n FROM `{CONSOLIDADA_TABLE}`"
        ).result()
        n = next(iter(result)).n
        if n > 0:
            return CheckResult(passed=True, message=f"consolidada_row_count: {n}")
        return CheckResult(
            passed=False, message="consolidada_row_count: 0 — tabela vazia"
        )
    except Exception as e:
        return CheckResult(
            passed=False, message=f"consolidada_row_count: erro na query — {e}"
        )


def validate(client: bigquery.Client) -> QualityGateResult:
    """Executa todos os checks e retorna resultado agregado.

    Graceful degradation: cada check é independente. Se o próprio check
    lança exceção, é tratada internamente e contabilizada como falha.

    Args:
        client: Cliente BigQuery autenticado.

    Returns:
        QualityGateResult com passed=True se todos os checks passaram,
        ou passed=False com lista de mensagens de falha.
    """
    checks = [
        _check_gold_row_count(client),
        _check_gold_freshness(client),
        _check_consolidada_row_count(client),
    ]

    failures = [c.message for c in checks if not c.passed]
    passed = len(failures) == 0

    if passed:
        logger.info(
            "[QUALITY_GATE] [SUCESSO] Todos os checks passaram: %s",
            " | ".join(c.message for c in checks),
        )
    else:
        logger.warning(
            "[QUALITY_GATE] [FALHA] %d check(s) falharam: %s",
            len(failures),
            " | ".join(failures),
        )

    return QualityGateResult(passed=passed, failures=failures)
