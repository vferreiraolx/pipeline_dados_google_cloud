"""Módulo de disparo de refresh do Tableau Cloud após conclusão do pipeline.

Responsabilidade única: acionar o refresh de um workbook publicado no Tableau
Cloud via Personal Access Token (PAT). Nunca propaga exceção — falha silenciosa
com log detalhado (o pipeline continua mesmo se o Tableau falhar).

Variáveis de ambiente (mesmas usadas pelo GitHub Actions e scripts/_tableau_refresh.py):
    TABLEAU_SERVER_URL   : ex. https://us-east-1.online.tableau.com
    TABLEAU_SITE_NAME    : nome do site (ex. olxbrasil)
    TABLEAU_TOKEN_NAME   : nome do PAT criado no Tableau Online
    TABLEAU_TOKEN_SECRET : segredo do PAT
    TABLEAU_WORKBOOK_ID  : LUID do workbook a ser atualizado
                           (SALA DE CONTROLE COMERCIAL: ed88bc32-b87e-47da-9ef5-434136acbd91)

Quando TABLEAU_WORKBOOK_ID não está configurado, retorna imediatamente com
triggered=False sem tentar autenticar.
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TableauTriggerResult:
    """Resultado da tentativa de disparo de refresh do Tableau.

    Attributes:
        triggered: True se o job de refresh foi iniciado com sucesso.
        job_id: ID do job de refresh retornado pelo Tableau (quando triggered=True).
        error: Mensagem de erro (quando triggered=False).
    """

    triggered: bool
    job_id: Optional[str] = None
    error: Optional[str] = None


def trigger_refresh(workbook_id: str) -> TableauTriggerResult:
    """Aciona o refresh de um workbook publicado no Tableau Cloud.

    Usa Personal Access Token (PAT) para autenticação. Alinha com a convenção
    de variáveis de ambiente já usada no projeto (TABLEAU_TOKEN_NAME,
    TABLEAU_TOKEN_SECRET) e com o padrão do TableauClient em
    src/integrations/tableau_client.py.

    Graceful degradation: nunca lança exceção. Todos os erros são
    capturados e retornados em TableauTriggerResult.error.

    Args:
        workbook_id: LUID do workbook no Tableau Cloud.
                     Obtido de TABLEAU_WORKBOOK_ID no ambiente.
                     SALA DE CONTROLE COMERCIAL: ed88bc32-b87e-47da-9ef5-434136acbd91

    Returns:
        TableauTriggerResult com triggered=True e job_id quando o refresh
        foi iniciado com sucesso, ou triggered=False com error descritivo.
    """
    if not workbook_id:
        logger.info(
            "[TABLEAU_TRIGGER] [SKIP] TABLEAU_WORKBOOK_ID não configurado "
            "— refresh ignorado"
        )
        return TableauTriggerResult(triggered=False, error="not_configured")

    server_url = os.getenv("TABLEAU_SERVER_URL", "")
    site_name = os.getenv("TABLEAU_SITE_NAME", "")
    token_name = os.getenv("TABLEAU_TOKEN_NAME", "")
    token_secret = os.getenv("TABLEAU_TOKEN_SECRET", "")

    missing = [
        k for k, v in {
            "TABLEAU_SERVER_URL": server_url,
            "TABLEAU_SITE_NAME": site_name,
            "TABLEAU_TOKEN_NAME": token_name,
            "TABLEAU_TOKEN_SECRET": token_secret,
        }.items()
        if not v
    ]
    if missing:
        msg = f"Variáveis ausentes: {', '.join(missing)}"
        logger.warning("[TABLEAU_TRIGGER] [SKIP] %s", msg)
        return TableauTriggerResult(triggered=False, error=msg)

    try:
        import tableauserverclient as TSC  # lazy import — opcional em dev/test

        tableau_auth = TSC.PersonalAccessTokenAuth(
            token_name=token_name,
            personal_access_token=token_secret,
            site_id=site_name,
        )
        server = TSC.Server(server_url, use_server_version=True)

        logger.info(
            "[TABLEAU_TRIGGER] [INICIO] Conectando em %s (site=%s) "
            "para refresh workbook=%s",
            server_url,
            site_name,
            workbook_id,
        )

        with server.auth.sign_in(tableau_auth):
            # Trigger refresh assíncrono (não aguarda conclusão do job)
            job = server.workbooks.refresh(workbook_id)

            job_id = str(job.id) if job and job.id else None
            logger.info(
                "[TABLEAU_TRIGGER] [SUCESSO] Refresh iniciado | "
                "workbook=%s | job_id=%s",
                workbook_id,
                job_id,
            )
            return TableauTriggerResult(triggered=True, job_id=job_id)

    except ImportError:
        msg = "tableauserverclient não instalado"
        logger.error("[TABLEAU_TRIGGER] [FALHA] %s", msg)
        return TableauTriggerResult(triggered=False, error=msg)

    except Exception as e:
        msg = str(e)
        logger.error(
            "[TABLEAU_TRIGGER] [FALHA] workbook=%s | erro=%s",
            workbook_id,
            msg,
        )
        return TableauTriggerResult(triggered=False, error=msg)
