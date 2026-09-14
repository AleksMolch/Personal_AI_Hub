"""Анализ таблиц (CSV/XLSX) через DuckDB в изолированном read-only режиме.

Модель получает schema и агрегированные результаты, а не всю таблицу.
Запрещены файловые функции и сеть (enable_external_access=false), разрешён
только SELECT, результат ограничен по числу строк/ячеек.
"""
from __future__ import annotations

import csv
import io
import json
import re
from decimal import Decimal

import duckdb

MAX_ROWS = 1000
MAX_SAMPLE_ROWS = 5
MAX_RESULT_CELLS = 200_000


class TableQueryError(Exception):
    """Некорректный или запрещённый SQL-запрос."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "INVALID_TABLE_QUERY"


class UnsupportedTableFormatError(Exception):
    """Формат файла не поддерживается для анализа таблиц."""

    def __init__(self, fmt: str) -> None:
        super().__init__(f"неподдерживаемый формат таблицы: {fmt}")
        self.code = "UNSUPPORTED_TABLE_FORMAT"


_FORBIDDEN_KEYWORDS = {
    "CREATE", "DROP", "INSERT", "UPDATE", "DELETE", "ALTER", "TRUNCATE",
    "COPY", "ATTACH", "DETACH", "INSTALL", "LOAD", "PRAGMA", "EXPORT",
    "IMPORT", "CALL", "SET", "RESET", "BEGIN", "COMMIT", "ROLLBACK",
    "VACUUM", "USE", "GRANT", "REVOKE", "TRANSACTION",
}


def validate_sql(sql: str) -> None:
    """Проверяет, что запрос — единственный SELECT/WITH без запрещённых слов."""
    cleaned = _strip_comments(sql).strip()
    if not cleaned:
        raise TableQueryError("Пустой запрос.")
    if ";" in cleaned:
        raise TableQueryError("Разрешён только один запрос (без ';').")

    upper = cleaned.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        raise TableQueryError("Разрешены только SELECT/WITH запросы.")

    for word in re.findall(r"[A-Za-z]+", upper):
        if word in _FORBIDDEN_KEYWORDS:
            raise TableQueryError(f"Запрещённое ключевое слово: {word}")


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql


def _new_connection() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    conn.execute("SET enable_external_access=false")
    return conn


def load_table(path: str, fmt: str, sheet: str | None = None) -> duckdb.DuckDBPyConnection:
    """Загружает файл в DuckDB как таблицу `data`.

    Файл читается в Python (не DuckDB), поэтому `enable_external_access=false`
    действует всегда и DuckDB не имеет доступа к файловой системе.
    """
    conn = _new_connection()
    if fmt == "csv":
        columns, rows = _read_csv(path)
        _create_table_from_rows(conn, columns, rows)
    elif fmt in {"xlsx", "xls"}:
        columns, rows = _read_xlsx(path, sheet)
        _create_table_from_rows(conn, columns, rows)
    else:
        raise UnsupportedTableFormatError(fmt)
    return conn


def _read_csv(path: str) -> tuple[list[str], list[list]]:
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(fh, dialect)
        rows = [row for row in reader if any(cell != "" for cell in row)]
    if not rows:
        return [], []
    header = [str(h) if h else f"col_{i}" for i, h in enumerate(rows[0])]
    return header, rows[1:]


def xlsx_sheet_names(path: str) -> list[str]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    return wb.sheetnames


def _read_xlsx(path: str, sheet: str | None) -> tuple[list[str], list[list]]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    if not rows:
        return [], []
    header = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    return header, rows[1:]


def _infer_duckdb_type(values: list) -> str:
    non_null = [v for v in values if v is not None]
    if not non_null:
        return "VARCHAR"
    if all(isinstance(v, bool) for v in non_null):
        return "BOOLEAN"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in non_null):
        return "BIGINT"
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in non_null):
        return "DOUBLE"
    return "VARCHAR"


def _parse_cell(value):
    """Приводит строковое значение к числу/булеву, если возможно."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    text = str(value).strip()
    if text == "":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _coerce_to_type(value, duckdb_type: str):
    if value is None:
        return None
    if duckdb_type == "BIGINT":
        return int(value)
    if duckdb_type == "DOUBLE":
        return float(value)
    if duckdb_type == "BOOLEAN":
        return bool(value)
    return str(value)


def _create_table_from_rows(conn, columns: list[str], rows: list[list]) -> None:
    if not columns:
        conn.execute("CREATE TABLE data AS SELECT 1 AS empty LIMIT 0")
        return
    cols = list(columns)
    for row in rows:
        while len(row) < len(cols):
            row.append(None)
        if len(row) > len(cols):
            row[:] = row[: len(cols)]

    # Парсинг ячеек (строки -> числа), затем вывод типов.
    candidates = [[_parse_cell(c) for c in row] for row in rows]
    defs = []
    col_types = []
    for i, name in enumerate(cols):
        col_type = _infer_duckdb_type([r[i] for r in candidates])
        col_types.append(col_type)
        defs.append(f'"{_sanitize_column(name, i)}" {col_type}')

    conn.execute(f"CREATE TABLE data ({', '.join(defs)})")
    if candidates:
        placeholders = ", ".join(["?"] * len(cols))
        coerced = [
            tuple(_coerce_to_type(c, col_types[i]) for i, c in enumerate(row))
            for row in candidates
        ]
        conn.executemany(f"INSERT INTO data VALUES ({placeholders})", coerced)


def _sanitize_column(name: str, index: int) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_а-яА-Я]", "_", name)
    return clean or f"col_{index}"


def schema_preview(conn) -> dict:
    """Возвращает колонки, типы и пример строк."""
    desc = conn.execute("DESCRIBE data").fetchall()
    columns = [{"name": d[0], "type": d[1]} for d in desc]
    sample = conn.execute(f"SELECT * FROM data LIMIT {MAX_SAMPLE_ROWS}").fetchall()
    count = conn.execute("SELECT count(*) FROM data").fetchone()[0]
    return {
        "columns": columns,
        "sample_rows": _json_safe(sample),
        "row_count": int(count),
    }


def run_query(conn, sql: str) -> dict:
    """Выполняет SELECT-запрос с лимитом строк."""
    validate_sql(sql)
    wrapped = f"SELECT * FROM ({sql}) LIMIT {MAX_ROWS}"
    result = conn.execute(wrapped)
    columns = [d[0] for d in result.description]
    rows = _json_safe(result.fetchall())
    if len(rows) * max(len(columns), 1) > MAX_RESULT_CELLS:
        raise TableQueryError("Результат слишком большой.")
    return {"columns": columns, "rows": rows}


def export_csv(conn, sql: str) -> str:
    """Выполняет запрос и возвращает CSV-строку."""
    validate_sql(sql)
    result = conn.execute(f"SELECT * FROM ({sql}) LIMIT {MAX_ROWS}")
    columns = [d[0] for d in result.description]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in result.fetchall():
        writer.writerow(list(row))
    return buf.getvalue()


def export_xlsx(conn, sql: str) -> bytes:
    """Выполняет запрос и возвращает XLSX-байты."""
    import openpyxl

    validate_sql(sql)
    result = conn.execute(f"SELECT * FROM ({sql}) LIMIT {MAX_ROWS}")
    columns = [d[0] for d in result.description]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(columns)
    for row in result.fetchall():
        ws.append(list(row))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _json_safe(rows: list) -> list:
    out = []
    for row in rows:
        out.append([_json_value(v) for v in row])
    return out


def _json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):  # date/datetime/time
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value
