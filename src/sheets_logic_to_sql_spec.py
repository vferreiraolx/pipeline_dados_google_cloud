"""
Gera especificacao para migracao de calculos de Google Sheets para SQL.

Entrada esperada: JSON produzido por sheets_structure_inspector.py com
--include-formulas --json.

Saida:
- Relatorio em Markdown com regras de calculo por aba.
- Tabela de mapeamento sugerindo expressoes SQL para formulas identificadas.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


CELL_REF_RE = re.compile(r"(?<![A-Z0-9_])([$]?)([A-Z]{1,3})([$]?)(\d+)")
FUNC_CALL_RE = re.compile(r"([A-Z][A-Z0-9_]*)\s*\(")

KNOWN_FUNCTIONS = {
    "ABS",
    "AND",
    "CASE",
    "COALESCE",
    "CONCAT",
    "DATE",
    "EXTRACT",
    "FLOOR",
    "IF",
    "IFERROR",
    "LEFT",
    "LENGTH",
    "LOWER",
    "MAX",
    "MIN",
    "NOT",
    "NULLIF",
    "OR",
    "POWER",
    "REGEXP_REPLACE",
    "REPLACE",
    "RIGHT",
    "ROUND",
    "SAFE_DIVIDE",
    "SUBSTR",
    "SUM",
    "TRIM",
    "UPPER",
}


@dataclass
class ConversionResult:
    sql_expression: str
    confidence: str
    notes: list[str]


def _split_args(args_text: str) -> list[str]:
    """Divide argumentos respeitando parenteses internos."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0

    for ch in args_text:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    if current:
        parts.append("".join(current).strip())
    return parts


def _replace_sheet_cell_refs_with_columns(expr: str, headers: list[str]) -> str:
    def _replace(match: re.Match) -> str:
        col_letters = match.group(2)
        col_index = _column_to_index(col_letters)
        if 1 <= col_index <= len(headers):
            header = headers[col_index - 1].strip()
            if header:
                safe = header.lower().strip()
                safe = re.sub(r"[^a-z0-9_]+", "_", safe)
                safe = re.sub(r"_+", "_", safe).strip("_")
                if safe:
                    return safe
        return f"col_{col_letters.lower()}"

    return CELL_REF_RE.sub(_replace, expr)


def _column_to_index(col: str) -> int:
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def _convert_if(expr: str) -> str:
    inside = expr[len("IF("):-1]
    args = _split_args(inside)
    if len(args) != 3:
        return expr
    return f"(CASE WHEN {args[0]} THEN {args[1]} ELSE {args[2]} END)"


def _convert_iferror(expr: str) -> str:
    inside = expr[len("IFERROR("):-1]
    args = _split_args(inside)
    if len(args) != 2:
        return expr
    return f"COALESCE({args[0]}, {args[1]})"


def _convert_sum(expr: str) -> str:
    inside = expr[len("SUM("):-1]
    args = _split_args(inside)
    if not args:
        return expr
    return "(" + " + ".join(args) + ")"


def _convert_formula_to_sql(formula: str, headers: list[str]) -> ConversionResult:
    notes: list[str] = []
    raw = formula.strip()
    if raw.startswith("="):
        raw = raw[1:]

    expr = raw.replace("^", " POWER ")
    expr = expr.replace("<>", "!=")

    # Conversoes principais de funcoes.
    if expr.startswith("IF(") and expr.endswith(")"):
        expr = _convert_if(expr)
        notes.append("IF convertido para CASE WHEN")
    if expr.startswith("IFERROR(") and expr.endswith(")"):
        expr = _convert_iferror(expr)
        notes.append("IFERROR convertido para COALESCE")
    if expr.startswith("SUM(") and expr.endswith(")"):
        expr = _convert_sum(expr)
        notes.append("SUM simples convertido para soma aritmetica")

    expr = _replace_sheet_cell_refs_with_columns(expr, headers)

    used_funcs = {m.group(1).upper() for m in FUNC_CALL_RE.finditer(raw)}
    unknown_funcs = sorted(f for f in used_funcs if f not in KNOWN_FUNCTIONS)

    confidence = "alta"
    if unknown_funcs:
        confidence = "baixa"
        notes.append(
            "Funcoes nao mapeadas detectadas: " + ", ".join(unknown_funcs)
        )
    elif used_funcs and used_funcs.intersection({"IF", "IFERROR", "SUM"}):
        confidence = "media"

    if " POWER " in expr:
        notes.append("Operador ^ ajustado; valide semantica no banco alvo")

    return ConversionResult(
        sql_expression=expr,
        confidence=confidence,
        notes=notes,
    )


def _build_markdown_report(payload: dict) -> str:
    lines: list[str] = []
    lines.append(f"# Especificacao Sheets -> SQL: {payload.get('spreadsheet_title', '(sem titulo)')}")
    lines.append("")
    lines.append(f"- Spreadsheet ID: {payload.get('spreadsheet_id', '(nao informado)')}")
    lines.append(f"- Total de abas: {payload.get('worksheet_count', 0)}")
    lines.append("")

    worksheets = payload.get("worksheets", [])
    if not worksheets:
        lines.append("Nenhuma aba encontrada no JSON de entrada.")
        return "\n".join(lines)

    for ws in worksheets:
        ws_name = ws.get("name", "(sem nome)")
        headers = ws.get("headers", [])
        lines.append(f"## Aba: {ws_name}")
        lines.append("")
        lines.append(
            "- Estrutura: "
            f"{ws.get('rows_with_data', 0)} linhas, "
            f"{ws.get('columns_with_data', 0)} colunas"
        )
        lines.append(
            "- Colunas calculadas: "
            + (", ".join(ws.get("formula_columns", []))
               if ws.get("formula_columns")
               else "nenhuma")
        )
        lines.append(f"- Total de celulas com formula: {ws.get('formula_cells_count', 0)}")
        lines.append("")

        patterns = ws.get("formula_patterns", [])
        if not patterns:
            lines.append("Sem formulas detectadas para conversao nesta aba.")
            lines.append("")
            continue

        lines.append("| Coluna alvo | Formula exemplo | SQL sugerido | Confianca | Observacoes |")
        lines.append("|---|---|---|---|---|")

        for pattern in patterns:
            formula = pattern.get("example_formula") or ""
            target_col = pattern.get("example_column") or "(nao identificado)"
            result = _convert_formula_to_sql(formula, headers)
            notes = "; ".join(result.notes) if result.notes else "-"

            lines.append(
                "| "
                f"{target_col} | "
                f"{formula.replace('|', '\\|')} | "
                f"{result.sql_expression.replace('|', '\\|')} | "
                f"{result.confidence} | "
                f"{notes.replace('|', '\\|')} |"
            )

        lines.append("")
        lines.append("Recomendacao: validar cada expressao no dataset de staging antes de promover.")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Converte analise de formulas do Sheets em especificacao SQL."
    )
    parser.add_argument(
        "--input-json",
        required=True,
        help="Arquivo JSON gerado pelo sheets_structure_inspector.py",
    )
    parser.add_argument(
        "--output-md",
        required=True,
        help="Caminho do relatorio Markdown de saida",
    )
    args = parser.parse_args()

    try:
        in_path = Path(args.input_json)
        out_path = Path(args.output_md)

        payload = json.loads(in_path.read_text(encoding="utf-8"))
        report = _build_markdown_report(payload)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")

        print(f"Relatorio gerado: {out_path}")
        return 0
    except Exception as exc:
        print(f"Erro ao gerar especificacao SQL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
