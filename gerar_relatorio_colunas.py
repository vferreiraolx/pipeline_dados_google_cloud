"""
Script para gerar relatório das colunas das 4 tabelas extraídas no BigQuery.

Conecta no BigQuery, consulta o schema de cada tabela e gera um relatório
em Markdown na pasta docs/.

Uso:
    python gerar_relatorio_colunas.py
"""

from google.cloud import bigquery


PROJECT_ID = "conect-python-g-sheets"
DATASET = "planejamento_comercial"

TABELAS = [
    "re_gold_receita_unificado_air",
    "re_silver_receita_cb_air",
    "re_silver_planos_periodicos_cb",
    "re_silver_receita_cb_paids_air",
]


def get_table_schema(client: bigquery.Client, table_name: str) -> list[dict]:
    """Retorna lista de colunas com nome, tipo e descrição."""
    table_id = f"{PROJECT_ID}.{DATASET}.{table_name}"
    table = client.get_table(table_id)
    columns = []
    for field in table.schema:
        columns.append({
            "nome": field.name,
            "tipo": field.field_type,
            "modo": field.mode,
            "descricao": field.description or "",
        })
    return columns


def generate_markdown_report(all_schemas: dict[str, list[dict]]) -> str:
    """Gera relatório Markdown com as colunas de todas as tabelas."""
    lines = []
    lines.append("# Relatório de Colunas - Tabelas Extraídas")
    lines.append("")
    lines.append(f"**Projeto:** `{PROJECT_ID}`")
    lines.append(f"**Dataset:** `{DATASET}`")
    lines.append(f"**Total de tabelas:** {len(all_schemas)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for table_name, columns in all_schemas.items():
        lines.append(f"## {table_name}")
        lines.append("")
        lines.append(f"**Quantidade de colunas:** {len(columns)}")
        lines.append("")
        lines.append("| # | Coluna | Tipo | Modo | Descrição |")
        lines.append("|---|--------|------|------|-----------|")
        for i, col in enumerate(columns, 1):
            lines.append(
                f"| {i} | `{col['nome']}` | {col['tipo']} | {col['modo']} | {col['descricao']} |"
            )
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main():
    client = bigquery.Client(project=PROJECT_ID)
    all_schemas = {}

    print("Consultando schemas das tabelas no BigQuery...")
    for table_name in TABELAS:
        print(f"  -> {table_name}")
        try:
            schema = get_table_schema(client, table_name)
            all_schemas[table_name] = schema
            print(f"     {len(schema)} colunas encontradas")
        except Exception as e:
            print(f"     ERRO: {e}")
            all_schemas[table_name] = []

    report = generate_markdown_report(all_schemas)

    output_path = "docs/RELATORIO_COLUNAS.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\nRelatório gerado com sucesso: {output_path}")


if __name__ == "__main__":
    main()
