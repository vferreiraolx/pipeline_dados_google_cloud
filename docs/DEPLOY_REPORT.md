# Relatório de Deploy — Cloud Function Pipeline Dados Planejamento

**Data**: 01/07/2026  
**Projeto GCP**: `conect-python-g-sheets`  
**Região**: `us-east4`  
**Função**: `pipeline-dados-planejamento`

---

## Status Final: FUNCIONAL ✅ — Validado sem VPN (02/07/2026)

O pipeline está rodando end-to-end na cloud:
- Conexão com Trino via VPC Connector
- Extração de dados (845.840 registros na primeira tabela)
- Upload pro GCS (`gs://teste-extracao-trino/`)
- Carga no BigQuery (`planejamento_comercial`)

---

## Prova de Funcionamento sem VPN

**Teste realizado em 02/07/2026 às 22:48 UTC com VPN corporativa desligada.**

| Campo | Valor |
|-------|-------|
| Execution ID | `bkCES3cqjsMr` |
| VPN status | **DESLIGADA** |
| 22:48:26 UTC | `[CONEXÃO] [SUCESSO]` — Trino estabelecida via VPC |
| 22:48:28 UTC | `[EXTRAÇÃO] [INICIO]` — re_gold_receita_unificado_air |
| 22:49:03 UTC | `[EXTRAÇÃO] [SUCESSO]` — **845.840 registros** |
| 22:49:03 UTC | `[UPLOAD_GCS] [INICIO]` → `gs://teste-extracao-trino/...` |

O VPC Connector `trino-connector` (us-east4) roteia o tráfego pela rede interna do GCP diretamente ao gateway Trino da OLX, sem necessidade de túnel VPN.

---

## Configuração da Cloud Function

| Parâmetro | Valor |
|-----------|-------|
| Runtime | Python 3.11 (Gen2) |
| Memória | 4 GiB |
| CPU | 2 |
| Timeout | 540s |
| VPC Connector | `trino-connector` (us-east4) |
| Egress | ALL_TRAFFIC |
| Entry Point | `pipeline_handler` |
| URL | `https://us-east4-conect-python-g-sheets.cloudfunctions.net/pipeline-dados-planejamento` |

---

## Histórico de Problemas Resolvidos

### 1. VPC Connector — Org Policy bloqueava criação
- **Erro**: `PERMISSION_DENIED: vpcaccess.connectors.create`
- **Causa**: Organization Policy da OLX bloqueia mesmo com role Owner
- **Solução**: Thiago (infra) criou o connector `trino-connector` com subnet dedicada

### 2. Build — Arquivos com sintaxe inválida
- **Erro**: SyntaxError em `docs/teste_bd_planos_uf.py` e `src/sheets_logic_to_sql_spec.py`
- **Solução**: Criado `.gcloudignore` para excluir arquivos desnecessários do deploy

### 3. Credenciais Trino — Variáveis de ambiente ausentes
- **Erro**: `CredentialError: Variáveis de ambiente obrigatórias ausentes`
- **Solução**: Configuradas `TRINO_USER` e `TRINO_PASSWORD` como env vars na function

### 4. BigQuery — Service account sem permissão
- **Erro**: `403 Access Denied: bigquery.datasets.create`
- **Causa**: Service account `18795267438-compute@developer.gserviceaccount.com` sem role
- **Status**: Resolveu sozinho (provavelmente o dataset já existia do teste anterior)

### 5. Memória insuficiente
- **Erro**: `Memory limit of 1024 MiB exceeded`
- **Solução**: Aumentada de 1Gi para 4Gi

### 6. Type mismatch no Trino
- **Erro**: `Cannot apply operator: date = varchar(10)`
- **Causa**: Query incremental usava `WHERE dt = '2026-07-01'` (string) vs coluna tipo `date`
- **Solução**: Corrigido para `WHERE dt = DATE '2026-07-01'` em `src/trino_extractor.py`

---

## Como Fazer Redeploy (após ajustes em queries)

### Passo a passo:

**1. Editar os arquivos localmente**
- Abra o arquivo SQL ou Python que quer alterar
- Salve as alterações normalmente

**2. Abrir terminal na pasta do projeto**
```
cd c:\Users\vinicius.foreste\Desktop\Oswaldo_novo\projeto_sheets
```

**3. Rodar o comando de deploy**
```bash
gcloud functions deploy pipeline-dados-planejamento \
  --gen2 \
  --runtime=python311 \
  --region=us-east4 \
  --source=. \
  --entry-point=pipeline_handler \
  --trigger-http \
  --vpc-connector=projects/conect-python-g-sheets/locations/us-east4/connectors/trino-connector \
  --egress-settings=all \
  --timeout=540s \
  --memory=4Gi \
  --project=conect-python-g-sheets \
  --quiet
```

**4. Aguardar ~2-3 minutos** até ver a mensagem `Done` ou `Completed`

**5. Testar a function** (chamar manualmente pra ver se funciona):
```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://us-east4-conect-python-g-sheets.cloudfunctions.net/pipeline-dados-planejamento"
```

**6. Verificar logs** (se deu erro ou demorou):
```bash
gcloud functions logs read pipeline-dados-planejamento \
  --region=us-east4 \
  --project=conect-python-g-sheets \
  --limit=30
```

### Notas:
- O `.gcloudignore` já exclui arquivos desnecessários (docs, testes, csvs) automaticamente
- Se adicionar um novo arquivo `.sql` na pasta `sql/`, ele vai pro deploy automaticamente
- Se der erro de build (SyntaxError), adicione o arquivo problemático no `.gcloudignore`

---

## Como Verificar Funcionamento

### Ver logs em tempo real
```bash
gcloud functions logs read pipeline-dados-planejamento \
  --region=us-east4 \
  --project=conect-python-g-sheets \
  --limit=30
```

### Chamar a function manualmente
```bash
# No Cloud Shell (bash):
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://us-east4-conect-python-g-sheets.cloudfunctions.net/pipeline-dados-planejamento"

# No PowerShell local:
$token = (gcloud auth print-identity-token).Trim()
Invoke-RestMethod -Uri "https://us-east4-conect-python-g-sheets.cloudfunctions.net/pipeline-dados-planejamento" -Headers @{"Authorization"="Bearer $token"} -TimeoutSec 600
```

### Verificar dados no BigQuery
Acesse o BigQuery Console e consulte o dataset `planejamento_comercial`:
```sql
SELECT COUNT(*) FROM `conect-python-g-sheets.planejamento_comercial.re_gold_receita_unificado_air`
WHERE dt = CURRENT_DATE()
```

---

## Como Configurar o Cloud Scheduler

O Cloud Scheduler dispara a function automaticamente no horário desejado.

### Passo a passo:

**1. Verificar se a API do Scheduler está habilitada**
```bash
gcloud services enable cloudscheduler.googleapis.com --project=conect-python-g-sheets
```

**2. Criar o job agendado**
```bash
gcloud scheduler jobs create http pipeline-diario \
  --location=us-east4 \
  --schedule="0 8 * * 1-5" \
  --time-zone="America/Sao_Paulo" \
  --uri="https://us-east4-conect-python-g-sheets.cloudfunctions.net/pipeline-dados-planejamento" \
  --http-method=GET \
  --oidc-service-account-email=18795267438-compute@developer.gserviceaccount.com \
  --oidc-token-audience="https://us-east4-conect-python-g-sheets.cloudfunctions.net/pipeline-dados-planejamento" \
  --project=conect-python-g-sheets \
  --attempt-deadline=600s
```

**3. Confirmar que o job foi criado**
```bash
gcloud scheduler jobs list --location=us-east4 --project=conect-python-g-sheets
```

**4. Testar o agendamento manualmente (dispara agora)**
```bash
gcloud scheduler jobs run pipeline-diario --location=us-east4 --project=conect-python-g-sheets
```

**5. Ver se executou com sucesso**
```bash
gcloud functions logs read pipeline-dados-planejamento \
  --region=us-east4 \
  --project=conect-python-g-sheets \
  --limit=30
```

### Ajustar horário do schedule:

O formato é cron: `minuto hora dia mês dia_semana`

| Schedule | Significado |
|----------|-------------|
| `"0 8 * * 1-5"` | 8h seg-sex |
| `"0 7 * * *"` | 7h todo dia |
| `"30 9 * * 1-5"` | 9:30 seg-sex |
| `"0 8,14 * * 1-5"` | 8h e 14h seg-sex |
| `"0 6 * * 1-5"` | 6h seg-sex (antes do expediente) |

### Alterar horário de um job existente:
```bash
gcloud scheduler jobs update http pipeline-diario \
  --location=us-east4 \
  --schedule="0 7 * * 1-5" \
  --project=conect-python-g-sheets
```

### Pausar o job (sem deletar):
```bash
gcloud scheduler jobs pause pipeline-diario --location=us-east4 --project=conect-python-g-sheets
```

### Retomar o job:
```bash
gcloud scheduler jobs resume pipeline-diario --location=us-east4 --project=conect-python-g-sheets
```

### Deletar o job:
```bash
gcloud scheduler jobs delete pipeline-diario --location=us-east4 --project=conect-python-g-sheets
```

### Notas:
- O Scheduler usa a service account pra autenticar na function (OIDC token)
- Se a function retornar erro (5xx), o Scheduler NÃO re-tenta por padrão
- O `attempt-deadline=600s` define quanto tempo esperar pela resposta (10 min)
- Pode ver o histórico de execuções no Console: Cloud Scheduler → pipeline-diario → Logs

---

## Pontos de Atenção

1. **Timeout de 540s**: Se a extração completa da tabela `re_silver_receita_cb_air` ultrapassar 9 minutos, vai dar timeout. Considerar particionar a extração ou aumentar o timeout (máximo Cloud Functions Gen2: 3600s).

2. **Credenciais no env vars**: `TRINO_USER` e `TRINO_PASSWORD` estão como variáveis de ambiente (visíveis no describe da function). Para produção, considerar migrar para Secret Manager.

3. **Service Account**: A SA `18795267438-compute@developer.gserviceaccount.com` é a default do Compute. Se precisar de roles adicionais no futuro, pedir ao time de infra.

4. **Function antiga em `southamerica-east1`**: A function anterior nessa região pode ser deletada (não tem VPC connector e não funciona).
