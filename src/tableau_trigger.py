"""Módulo de disparo de refresh do Tableau Cloud após conclusão do pipeline.

Responsabilidade única: acionar o refresh de uma fonte de dados publicada no
Tableau Cloud via Personal Access Token (PAT). Nunca propaga exceção — falha
silenciosa com log detalhado (o pipeline continua mesmo se o Tableau falhar).

Configuração via variáveis de ambiente:
    TABLEAU_SERVER_URL   : ex. https://us-east-1.online.tableau.com
    TABLEAU_SITE_NAME    : nome do site (ex. olxbrasil)
    TABLEAU_PAT_NAME     : nome do PAT criado no Tableau Online
    TABLEAU_PAT_SECRET   : segredo do PAT
    TABLEAU_DATASOURCE_ID: LUID da fonte de dados a ser atualizada
                           (copiado da URL no Tableau Online:
                            /datasources/{LUID}/connections)

Quando TABLEAU_DATASOURCE_ID não está configurado, retorna immediately
triggered=False sem tentar autenticar — permite deploy sem credenciais Tableau.
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


def trigger_refresh(datasource_id: str) -> TableauTriggerResult:
    """Aciona o refresh de uma fonte de dados publicada no Tableau Cloud.

    Usa Personal Access Token (PAT) para autenticação. Se qualquer
    variável de ambiente obrigatória estiver ausente ou se datasource_id
    estiver vazio, retorna triggered=False sem tentar conectar.

    Graceful degradation: nunca lança exceção. Todos os erros são
    capturados e retornados em TableauTriggerResult.error.

    Args:
        datasource_id: LUID da fonte de dados no Tableau Cloud.
                       Obtido de TABLEAU_DATASOURCE_ID no ambiente.

    Returns:
        TableauTriggerResult com triggered=True e job_id quando o refresh
        foi iniciado com sucesso, ou triggered=False com error descritivo.
    """
    if not datasource_id:
        logger.info(
            "[TABLEAU_TRIGGER] [SKIP] TABLEAU_DATASOURCE_ID não configurado "
            "— refresh ignorado"
        )
        return TableauTriggerResult(triggered=False, error="not_configured")

    server_url = os.getenv("TABLEAU_SERVER_URL", "")
    site_name = os.getenv("TABLEAU_SITE_NAME", "")
    pat_name = os.getenv("TABLEAU_PAT_NAME", "")
    pat_secret = os.getenv("TABLEAU_PAT_SECRET", "")

    missing = [
        k for k, v in {
            "TABLEAU_SERVER_URL": server_url,
            "TABLEAU_SITE_NAME": site_name,
            "TABLEAU_PAT_NAME": pat_name,
            "TABLEAU_PAT_SECRET": pat_secret,
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
            token_name=pat_name,
            personal_access_token=pat_secret,
            site_id=site_name,
        )
        server = TSC.Server(server_url, use_server_version=True)

        logger.info(
            "[TABLEAU_TRIGGER] [INICIO] Conectando em %s (site=%s) "
            "para refresh datasource=%s",
            server_url,
            site_name,
            datasource_id,
        )

        with server.auth.sign_in(tableau_auth):
            # Busca o objeto datasource pelo LUID
            datasource = server.datasources.get_by_id(datasource_id)

            # Inicia job de refresh assíncrono (não aguarda conclusão)
            refresh_job = server.datasources.refresh(datasource)

            job_id = str(refresh_job.id) if refresh_job and refresh_job.id else None
            logger.info(
                "[TABLEAU_TRIGGER] [SUCESSO] Refresh iniciado | "
                "datasource=%s | job_id=%s",
                datasource_id,
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
            "[TABLEAU_TRIGGER] [FALHA] datasource=%s | erro=%s",
            datasource_id,
            msg,
        )
        return TableauTriggerResult(triggered=False, error=msg)
