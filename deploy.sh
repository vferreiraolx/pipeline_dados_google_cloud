#!/bin/bash

# =============================================================================
# Script de Deploy - Pipeline de Dados Planejamento Comercial
# =============================================================================
# Este script realiza o deploy da Cloud Function que executa o pipeline de dados.
# Projeto GCP: conect-python-g-sheets
# Região: southamerica-east1 (São Paulo)
# =============================================================================

set -e  # Interrompe execução em caso de erro

# -----------------------------------------------------------------------------
# Configurações do projeto
# -----------------------------------------------------------------------------
PROJECT_ID="conect-python-g-sheets"
REGION="southamerica-east1"
FUNCTION_NAME="pipeline-dados-planejamento"
ENTRY_POINT="pipeline_handler"
RUNTIME="python311"

# -----------------------------------------------------------------------------
# Verifica se as variáveis de ambiente de credenciais estão definidas
# O pipeline precisa de credenciais AD para se conectar ao Trino
# -----------------------------------------------------------------------------
if [ -z "$TRINO_USER" ]; then
    echo "[ERRO] Variável de ambiente TRINO_USER não está definida."
    echo "       Defina com: export TRINO_USER='seu_usuario_ad'"
    exit 1
fi

if [ -z "$TRINO_PASSWORD" ]; then
    echo "[ERRO] Variável de ambiente TRINO_PASSWORD não está definida."
    echo "       Defina com: export TRINO_PASSWORD='sua_senha_ad'"
    exit 1
fi

# -----------------------------------------------------------------------------
# Deploy da Cloud Function
# -----------------------------------------------------------------------------
echo "============================================="
echo " Iniciando deploy da Cloud Function"
echo " Projeto: ${PROJECT_ID}"
echo " Função:  ${FUNCTION_NAME}"
echo " Região:  ${REGION}"
echo "============================================="

gcloud functions deploy "${FUNCTION_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --runtime="${RUNTIME}" \
    --entry-point="${ENTRY_POINT}" \
    --trigger-http \
    --allow-unauthenticated \
    --timeout=540s \
    --memory=512MB \
    --max-instances=1 \
    --set-env-vars="TRINO_USER=${TRINO_USER},TRINO_PASSWORD=${TRINO_PASSWORD}" \
    --source=.

# Explicação das flags:
# --project            : Projeto GCP de destino (conect-python-g-sheets)
# --region             : Região do deploy (São Paulo para menor latência)
# --runtime            : Runtime Python 3.11 (compatível com dependências do projeto)
# --entry-point        : Função Python que será invocada (pipeline_handler em main.py)
# --trigger-http       : Função será acionada via requisição HTTP (pelo Cloud Scheduler)
# --allow-unauthenticated : Permite chamadas sem autenticação (configurar IAM se necessário)
# --timeout=540s       : Timeout de 9 minutos para execução completa do pipeline
#                        (extração Trino + upload GCS + carga BigQuery + derivadas + Sheets)
# --memory=512MB       : Memória alocada para processar lotes de 100k linhas
# --max-instances=1    : Máximo de 1 instância simultânea para evitar execuções concorrentes
#                        (Requisito 7.4: não iniciar nova execução enquanto anterior está em andamento)
# --set-env-vars       : Define variáveis de ambiente com credenciais AD para conexão Trino
#                        (Requisito 1.2: autenticação via variáveis de ambiente)
# --source             : Diretório com o código-fonte (diretório atual)

echo ""
echo "============================================="
echo " Deploy concluído com sucesso!"
echo " URL da função:"
echo " https://${REGION}-${PROJECT_ID}.cloudfunctions.net/${FUNCTION_NAME}"
echo "============================================="
