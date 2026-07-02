"""
Utilitario para inspecionar estrutura de uma planilha Google Sheets.

Lista abas, cabecalhos da primeira linha e dimensoes de dados
para facilitar auditoria e resumo de tabelas.

Opcionalmente, analisa formulas para identificar logica de calculo:
- quantidade de celulas calculadas
- colunas com formulas
- padroes de formula mais frequentes
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

CELL_REF_RE = re.compile(
    r"((?:'[^']+'|[A-Za-z0-9_]+)!|)([$]?[A-Za-z]{1,3})([$]?\d+)"
)


@dataclass
class WorksheetStructure:
    name: str
    rows_with_data: int
    columns_with_data: int
    headers: list[str]
    formula_cells_count: int
    formula_columns: list[str]
    formula_patterns: list[dict]


def _resolve_credentials_file(cli_value: str | None) -> str:
    """Resolve arquivo de credenciais a partir de argumento ou variaveis de ambiente."""
    if cli_value:
        return cli_value

    env_candidates = [
        os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
        os.getenv("GCP_CREDENTIALS_FILE"),
        os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"),
    ]
    for value in env_candidates:
        if value:
            return value

    default_path = "credentials.json"
    if os.path.isfile(default_path):
        return default_path

    raise FileNotFoundError(
        "Arquivo de credenciais nao encontrado. Informe --credentials-file "
        "ou defina GOOGLE_APPLICATION_CREDENTIALS."
    )


def _build_client(credentials_file: str) -> gspread.Client:
    credentials = Credentials.from_service_account_file(
        credentials_file,
        scopes=SCOPES,
    )
    return gspread.authorize(credentials)


def _column_index_to_name(index: int) -> str:
    """Converte indice 1-based em nome de coluna estilo Excel (A, B, ..., AA)."""
    if index < 1:
        return "?"

    name = ""
    current = index
    while current > 0:
        current, rem = divmod(current - 1, 26)
        name = chr(65 + rem) + name
    return name


def _a1_cell(row_idx: int, col_idx: int) -> str:
    return f"{_column_index_to_name(col_idx)}{row_idx}"


def _normalize_formula(formula: str) -> str:
    """Normaliza referencias de linha para agrupar formulas equivalentes."""

    def _replace(match: re.Match) -> str:
        sheet_prefix = match.group(1)
        column_ref = match.group(2)
        return f"{sheet_prefix}{column_ref}#"

    return CELL_REF_RE.sub(_replace, formula)


def _extract_formula_insights(
    formulas_grid: list[list[str]],
    headers: list[str],
    max_formula_samples: int,
    max_patterns: int,
) -> tuple[int, list[str], list[dict]]:
    formula_count = 0
    formula_columns: set[str] = set()
    pattern_counter: Counter[str] = Counter()
    first_seen_by_pattern: dict[str, dict] = {}

    for row_idx, row_values in enumerate(formulas_grid, start=1):
        for col_idx, raw_value in enumerate(row_values, start=1):
            if not isinstance(raw_value, str) or not raw_value.startswith("="):
                continue

            formula_count += 1
            header = headers[col_idx - 1] if col_idx - 1 < len(headers) else ""
            column_name = header or _column_index_to_name(col_idx)
            formula_columns.add(column_name)

            normalized = _normalize_formula(raw_value)
            pattern_counter[normalized] += 1

            if (
                normalized not in first_seen_by_pattern
                and len(first_seen_by_pattern) < max_formula_samples
            ):
                first_seen_by_pattern[normalized] = {
                    "cell": _a1_cell(row_idx, col_idx),
                    "column": column_name,
                    "formula": raw_value,
                }

    top_patterns = pattern_counter.most_common(max_patterns)
    formula_patterns: list[dict] = []
    for pattern, occurrences in top_patterns:
        first_seen = first_seen_by_pattern.get(pattern, {})
        formula_patterns.append(
            {
                "normalized_formula": pattern,
                "occurrences": occurrences,
                "example_cell": first_seen.get("cell"),
                "example_column": first_seen.get("column"),
                "example_formula": first_seen.get("formula"),
            }
        )

    return formula_count, sorted(formula_columns), formula_patterns


def inspect_spreadsheet(
    spreadsheet_id: str,
    credentials_file: str,
    include_formulas: bool = False,
    max_formula_samples: int = 50,
    max_patterns: int = 20,
) -> dict:
    gc = _build_client(credentials_file)
    spreadsheet = gc.open_by_key(spreadsheet_id)

    worksheets: list[WorksheetStructure] = []
    for ws in spreadsheet.worksheets():
        values = ws.get_all_values()
        rows_with_data = len(values)
        columns_with_data = max((len(row) for row in values), default=0)
        headers = values[0] if values else []

        formula_cells_count = 0
        formula_columns: list[str] = []
        formula_patterns: list[dict] = []

        if include_formulas and rows_with_data > 0 and columns_with_data > 0:
            last_cell = _a1_cell(rows_with_data, columns_with_data)
            formulas_grid = ws.get(
                f"A1:{last_cell}",
                value_render_option="FORMULA",
            )
            (
                formula_cells_count,
                formula_columns,
                formula_patterns,
            ) = _extract_formula_insights(
                formulas_grid=formulas_grid,
                headers=headers,
                max_formula_samples=max_formula_samples,
                max_patterns=max_patterns,
            )

        worksheets.append(
            WorksheetStructure(
                name=ws.title,
                rows_with_data=rows_with_data,
                columns_with_data=columns_with_data,
                headers=headers,
                formula_cells_count=formula_cells_count,
                formula_columns=formula_columns,
                formula_patterns=formula_patterns,
            )
        )

    return {
        "spreadsheet_id": spreadsheet_id,
        "spreadsheet_title": spreadsheet.title,
        "worksheet_count": len(worksheets),
        "formula_analysis_enabled": include_formulas,
        "worksheets": [asdict(ws) for ws in worksheets],
    }


def _print_text_report(result: dict) -> None:
    print(f"Planilha: {result['spreadsheet_title']}")
    print(f"Spreadsheet ID: {result['spreadsheet_id']}")
    print(f"Total de abas: {result['worksheet_count']}")
    print("-" * 60)

    for ws in result["worksheets"]:
        print(f"Aba: {ws['name']}")
        print(
            "  Estrutura: "
            f"{ws['rows_with_data']} linhas com dados, "
            f"{ws['columns_with_data']} colunas com dados"
        )
        print(f"  Cabecalhos: {', '.join(ws['headers']) if ws['headers'] else '(vazio)'}")

        if result.get("formula_analysis_enabled"):
            print(f"  Celulas com formula: {ws['formula_cells_count']}")
            print(
                "  Colunas calculadas: "
                f"{', '.join(ws['formula_columns']) if ws['formula_columns'] else '(nenhuma)'}"
            )
            if ws["formula_patterns"]:
                print("  Padroes de formula (top):")
                for pattern in ws["formula_patterns"]:
                    print(
                        "    - "
                        f"{pattern['occurrences']}x em {pattern['example_cell']} "
                        f"[{pattern['example_column']}] -> {pattern['example_formula']}"
                    )
        print("-" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspeciona estrutura de uma planilha Google Sheets."
    )
    parser.add_argument(
        "--spreadsheet-id",
        required=True,
        help="ID da planilha Google Sheets.",
    )
    parser.add_argument(
        "--credentials-file",
        default=None,
        help=(
            "Caminho do JSON da service account. "
            "Se omitido, usa GOOGLE_APPLICATION_CREDENTIALS."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime saida em JSON.",
    )
    parser.add_argument(
        "--include-formulas",
        action="store_true",
        help="Analisa formulas para mapear logica de calculo.",
    )
    parser.add_argument(
        "--max-formula-samples",
        type=int,
        default=50,
        help="Maximo de formulas de exemplo registradas.",
    )
    parser.add_argument(
        "--max-patterns",
        type=int,
        default=20,
        help="Maximo de padroes de formula na saida.",
    )

    args = parser.parse_args()

    try:
        credentials_file = _resolve_credentials_file(args.credentials_file)
        result = inspect_spreadsheet(
            spreadsheet_id=args.spreadsheet_id,
            credentials_file=credentials_file,
            include_formulas=args.include_formulas,
            max_formula_samples=args.max_formula_samples,
            max_patterns=args.max_patterns,
        )

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_text_report(result)
        return 0
    except Exception as exc:
        print(f"Erro ao inspecionar planilha: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
