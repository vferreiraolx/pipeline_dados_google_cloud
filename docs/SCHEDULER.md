# Agendamento do Pipeline de Dados

## Visão Geral

O pipeline de dados é executado automaticamente 6 vezes por dia durante o horário comercial, utilizando o **Cloud Scheduler** do Google Cloud Platform para disparar a **Cloud Function** que contém o pipeline.

## Horários de Execução

| Job | Horário (Brasília) | Cron Expression | Descrição |
|-----|-------------------|-----------------|-----------|
| `pipeline-dados-08h` | 08:00 | `0 8 * * *` | Primeira execução do dia |
| `pipeline-dados-10h` | 10:00 | `0 10 * * *` | Segunda execução |
| `pipeline-dados-12h` | 12:00 | `0 12 * * *` | Execução do meio-dia |
| `pipeline-dados-14h` | 14:00 | `0 14 * * *` | Quarta execução |
| `pipeline-dados-16h` | 16:00 | `0 16 * * *` | Quinta execução |
| `pipeline-dados-18h` | 18:00 | `0 18 * * *` | Última execução do dia |

**Timezone**: `America/Sao_Paulo` (horário de Brasília)

Os jobs executam todos os dias da semana (incluindo finais de semana). Para restringir a dias úteis, altere a expressão cron para `0 {hora} * * 1-5`.

## Arquitetura

```
Cloud Scheduler ──HTTP POST──> Cloud Function (pipeline-dados)
     (6 jobs)                      (max_instances=1)
```

### Fluxo de Execução

1. O Cloud Scheduler dispara uma requisição HTTP POST para a Cloud Function no horário configurado
2. A Cloud Function executa o pipeline completo (extração → upload → carga → derivadas → exportação)
3. A Cloud Function retorna HTTP 200 (sucesso) ou HTTP 500 (falha) ao Scheduler
4. O Scheduler registra o resultado da execução

## Controle de Concorrência

⚠️ **Execuções concorrentes NÃO são permitidas.**

A Cloud Function está configurada com `max_instances=1`, o que garante que apenas uma instância do pipeline pode estar rodando por vez. Isso significa que:

- Se o job das 10:00 disparar enquanto a execução das 08:00 ainda estiver em andamento, o Cloud Functions **não** iniciará uma nova instância concorrente.
- A requisição será enfileirada pelo Cloud Functions até que a instância atual termine.
- Isso protege contra duplicação de dados e inconsistências que ocorreriam se duas execuções processassem as mesmas tabelas simultaneamente.

### Por que max_instances=1?

O pipeline processa tabelas com deduplicação por partição `dt`. Se duas execuções rodassem em paralelo:
- Ambas poderiam tentar fazer DELETE + INSERT na mesma partição
- Poderia haver conflito de escrita no GCS e BigQuery
- O controle de estado (`is_first_load`) poderia ficar inconsistente

## Configuração de Timeout e Retry

| Parâmetro | Valor | Justificativa |
|-----------|-------|---------------|
| `attempt-deadline` | 1800s (30 min) | O pipeline completo pode levar vários minutos dependendo do volume de dados |
| `retry-count` | 0 | O pipeline possui lógica interna de retry por etapa; retentativas externas poderiam causar processamento duplicado |

## Como Configurar

### Pré-requisitos

1. CLI `gcloud` instalado e autenticado
2. Permissões de `Cloud Scheduler Admin` no projeto `conect-python-g-sheets`
3. Cloud Function já deployada (ver `deploy.sh`)

### Criar os Jobs

Execute o script de configuração:

```bash
chmod +x setup_scheduler.sh
./setup_scheduler.sh
```

O script criará automaticamente os 6 jobs no Cloud Scheduler.

### Verificar os Jobs Criados

```bash
gcloud scheduler jobs list \
    --project=conect-python-g-sheets \
    --location=southamerica-east1
```

## Operações Comuns

### Pausar um Job

```bash
gcloud scheduler jobs pause pipeline-dados-08h \
    --project=conect-python-g-sheets \
    --location=southamerica-east1
```

### Retomar um Job Pausado

```bash
gcloud scheduler jobs resume pipeline-dados-08h \
    --project=conect-python-g-sheets \
    --location=southamerica-east1
```

### Executar Manualmente (Fora do Horário)

```bash
gcloud scheduler jobs run pipeline-dados-08h \
    --project=conect-python-g-sheets \
    --location=southamerica-east1
```

### Alterar o Horário de um Job

```bash
gcloud scheduler jobs update http pipeline-dados-08h \
    --project=conect-python-g-sheets \
    --location=southamerica-east1 \
    --schedule="0 9 * * *"
```

### Excluir um Job

```bash
gcloud scheduler jobs delete pipeline-dados-08h \
    --project=conect-python-g-sheets \
    --location=southamerica-east1
```

### Ver Histórico de Execuções

O histórico de execuções do Scheduler pode ser consultado no Console do GCP:
1. Acesse: https://console.cloud.google.com/cloudscheduler
2. Selecione o projeto `conect-python-g-sheets`
3. Clique no job desejado para ver o histórico

## Troubleshooting

### Job falha com timeout

Se o job falhar por timeout (execução > 30 minutos):
- Verifique os logs da Cloud Function no Cloud Logging
- Considere se o volume de dados aumentou significativamente
- Se necessário, aumente o `attempt-deadline` do job

### Job dispara mas Cloud Function não executa

Possíveis causas:
- Cloud Function não está deployada ou está com erro
- URL da Cloud Function está incorreta no job
- Permissões de invocação não estão configuradas

Verifique:
```bash
gcloud functions describe pipeline-dados \
    --project=conect-python-g-sheets \
    --region=southamerica-east1
```

### Execução anterior ainda está rodando

Se a execução anterior não terminou antes do próximo horário:
- Isso é esperado e seguro — `max_instances=1` impede concorrência
- A nova requisição ficará na fila até a instância atual liberar
- Verifique nos logs se a execução anterior está travada ou apenas processando um volume maior de dados
