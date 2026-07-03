"""
Entry point da Cloud Function para o Pipeline de Dados.

Expõe a função HTTP `pipeline_handler` que é invocada pelo
Cloud Scheduler nos horários agendados. Carrega a configuração,
instancia o Orchestrator e executa o pipeline completo.

Retorna HTTP 200 em sucesso com relatório de execução (JSON),
ou HTTP 500 em caso de falha com detalhes do erro.
"""

import json
import os
import traceback

from src.config_manager import ConfigManager
from src.exceptions import ConfigValidationError
from src.orchestrator import Orchestrator


def pipeline_handler(request):
    """Handler HTTP para Cloud Function.

    Executa o pipeline completo de dados: extração via Trino,
    upload para GCS, carga no BigQuery, tabelas derivadas e
    exportação para Google Sheets.

    Args:
        request: Objeto de requisição HTTP do Flask (fornecido
            automaticamente pelo Cloud Functions).

    Returns:
        Tupla (body, status_code, headers) onde:
        - body: JSON com relatório de execução ou detalhes do erro.
        - status_code: 200 para sucesso, 500 para falha.
        - headers: Content-Type application/json.
    """
    headers = {"Content-Type": "application/json"}

    try:
        # Carregar configuração do mesmo diretório que main.py
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "config.yaml"
        )
        config = ConfigManager(config_path)

        # Determinar grupo de execução: "hourly" | "daily" | "all"
        group = request.args.get("group", "all")

        # Bootstrap mensal opcional: "YYYY-MM" para carga histórica incremental.
        # Quando informado, apenas tabelas com historical=True são processadas
        # para aquele mês específico usando WRITE_APPEND (sem risco de OOM).
        bootstrap_month = request.args.get("bootstrap_month")

        # Instanciar e executar o pipeline
        orchestrator = Orchestrator(config)
        report = orchestrator.run(group=group, bootstrap_month=bootstrap_month)
        report["group"] = group
        if bootstrap_month:
            report["bootstrap_month"] = bootstrap_month

        return (json.dumps(report, ensure_ascii=False), 200, headers)

    except ConfigValidationError as e:
        error_response = {
            "status": "erro",
            "etapa": "validação_configuração",
            "mensagem": str(e),
        }
        return (json.dumps(error_response, ensure_ascii=False), 500, headers)

    except Exception as e:
        error_response = {
            "status": "erro",
            "etapa": "execução_pipeline",
            "mensagem": f"Erro inesperado durante a execução do pipeline: {type(e).__name__}",
            "detalhe": str(e),
        }
        return (json.dumps(error_response, ensure_ascii=False), 500, headers)


if __name__ == "__main__":
    """Bloco para execução local/teste do pipeline."""

    class _FakeRequest:
        """Requisição simulada para testes locais."""

        method = "GET"
        args = {}
        data = b""

    print("Iniciando execução local do pipeline...")
    body, status, _ = pipeline_handler(_FakeRequest())
    print(f"Status: {status}")
    print(f"Resposta: {body}")
