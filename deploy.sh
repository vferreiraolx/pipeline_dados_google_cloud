#!/bin/bash

# =============================================================================
# Script de Deploy - Pipeline de Dados Planejamento Comercial
# =============================================================================
# Este script realiza o deploy da Cloud Function que executa o pipeline de dados.
# Projeto GCP: conect-python-g-sheets
# Região: us-east4 (Virginia — mesma região do VPC Connector trino-connector)
# =============================================================================

set -e  # Interrompe execução em caso de erro

# -----------------------------------------------------------------------------
# Configurações do projeto
# -----------------------------------------------------------------------------
PROJECT_ID="conect-python-g-sheets"
REGION="us-east4"
FUNCTION_NAME="pipeline-dados-planejamento"
ENTRY_POINT="pipeline_handler"
RUNTIME="python311"
VPC_CONNECTOR="projects/${PROJECT_ID}/locations/${REGION}/connectors/trino-connector"

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
    --gen2 \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --runtime="${RUNTIME}" \
    --entry-point="${ENTRY_POINT}" \
    --trigger-http \
    --vpc-connector="${VPC_CONNECTOR}" \
    --egress-settings=all \
    --timeout=3600s \
    --memory=4Gi \
    --max-instances=1 \
    --set-env-vars="TRINO_USER=${TRINO_USER},TRINO_PASSWORD=${TRINO_PASSWORD}" \
    --source=.

# Explicação das flags:
# --gen2               : Cloud Functions 2ª geração (baseada em Cloud Run)
# --region             : us-east4 — mesma região do VPC Connector trino-connector
# --trigger-http       : Acionada por HTTP (Cloud Scheduler)
# --vpc-connector      : VPC Connector para acesso ao Trino sem VPN
# --egress-settings=all: Todo tráfego egress via VPC (necessário para Trino Gateway)
# --timeout=3600s      : 1 hora — suficiente para extração full das tabelas silver
#                        (grupo daily: ~1.25M linhas + upload GCS + carga BQ)
#                        (grupo hourly: termina em ~90s — timeout não é limitante)
# --memory=4Gi         : Necessário para processar 1.25M linhas em memória
# --max-instances=1    : Evita execuções concorrentes que corrompem tmp/ e estado

FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" \
    --gen2 --region="${REGION}" --project="${PROJECT_ID}" \
    --format="value(serviceConfig.uri)")

echo ""
echo "============================================="
echo " Deploy concluído com sucesso!"
echo " URL: ${FUNCTION_URL}"
echo "============================================="

# -----------------------------------------------------------------------------
# Cloud Scheduler — dois jobs com grupos separados
# -----------------------------------------------------------------------------
echo ""
echo "Configurando Cloud Scheduler..."

SA_EMAIL=$(gcloud iam service-accounts list \
    --project="${PROJECT_ID}" \
    --filter="email~pipeline" \
    --format="value(email)" | head -1)

# Fallback: usar service account padrão do projeto
if [ -z "$SA_EMAIL" ]; then
    PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
    SA_EMAIL="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi

echo " Service account: ${SA_EMAIL}"

# Job 1: hourly — extrai apenas re_gold (rápido, incremental)
# Atualiza ou cria o job existente
gcloud scheduler jobs describe "pipeline-hourly" \
    --location="${REGION}" --project="${PROJECT_ID}" > /dev/null 2>&1 \
    && UPDATE_OR_CREATE="update" || UPDATE_OR_CREATE="create"

gcloud scheduler jobs ${UPDATE_OR_CREATE} http "pipeline-hourly" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --schedule="0 * * * *" \
    --time-zone="America/Sao_Paulo" \
    --uri="${FUNCTION_URL}?group=hourly" \
    --http-method=POST \
    --oidc-service-account-email="${SA_EMAIL}" \
    --description="Extração horária: re_gold_receita_unificado_air (incremental, ~90s)"

echo " ✅ Job pipeline-hourly configurado (a cada hora)"

# Job 2: daily — extrai silver + custom SQL (extração completa, requer ~30-60min)
gcloud scheduler jobs describe "pipeline-daily" \
    --location="${REGION}" --project="${PROJECT_ID}" > /dev/null 2>&1 \
    && UPDATE_OR_CREATE="update" || UPDATE_OR_CREATE="create"

gcloud scheduler jobs ${UPDATE_OR_CREATE} http "pipeline-daily" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --schedule="0 3 * * *" \
    --time-zone="America/Sao_Paulo" \
    --uri="${FUNCTION_URL}?group=daily" \
    --http-method=POST \
    --oidc-service-account-email="${SA_EMAIL}" \
    --description="Extração diária às 03h BRT: silver + custom SQL (extração completa)"

echo " ✅ Job pipeline-daily configurado (diário às 03:00 BRT)"
echo ""
echo "Para bootstrap manual do grupo daily (execute uma vez após o deploy):"
echo "  curl -X POST '${FUNCTION_URL}?group=daily' \\"
echo "    -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\""
