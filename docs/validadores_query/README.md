# Validadores de Query

Scripts Python usados para validar as tabelas geradas pelo pipeline contra os CSVs exportados do Google Sheets.

## Como usar

1. Exporte a aba do Sheets como CSV
2. Edite o `csv_path` no script correspondente
3. Rode: `python docs/validadores_query/validar_<tabela>.py`

## Scripts disponíveis

- `validar_receita_enriquecida.py` — Compara totais de faturado/pago por mês
- `validar_diarizacao.py` — Compara pivot diário NOVO/CHURN/UP/DOWN
- `validar_bd_full.py` — Compara contagens e valores por Canal/Mês
- `validar_trino_snapshot.py` — Script legado de validação de snapshot

## Resultado esperado

- Valores financeiros (faturado_mes, pago_*): devem bater 100% (no centavo)
- Contagens (# Base Inicial, # Novos, # Churn): margem de ±0.3% (snapshot)
- Volume transcorrido: margem de ±4% (campos cohort ausentes)
