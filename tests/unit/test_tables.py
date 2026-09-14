"""Тесты табличного анализа: валидация SQL и работа с DuckDB."""
from __future__ import annotations

import pytest

from personal_hub.tables import (
    TableQueryError,
    export_csv,
    load_table,
    run_query,
    schema_preview,
    validate_sql,
)


def test_validate_sql_ok() -> None:
    validate_sql("SELECT * FROM data")
    validate_sql("WITH x AS (SELECT 1) SELECT * FROM x")


def test_validate_sql_rejects_non_select() -> None:
    with pytest.raises(TableQueryError):
        validate_sql("DELETE FROM data")
    with pytest.raises(TableQueryError):
        validate_sql("INSERT INTO data VALUES (1)")


def test_validate_sql_rejects_multiple_statements() -> None:
    with pytest.raises(TableQueryError):
        validate_sql("SELECT 1; DROP TABLE data")


def test_validate_sql_rejects_forbidden_keywords() -> None:
    with pytest.raises(TableQueryError):
        validate_sql("COPY data TO 'file.csv'")
    with pytest.raises(TableQueryError):
        validate_sql("ATTACH 'other.db'")


def test_csv_preview_and_query(tmp_path) -> None:
    path = tmp_path / "test.csv"
    path.write_text("name,value\na,1\nb,2\nc,3\n")

    conn = load_table(str(path), "csv")
    preview = schema_preview(conn)
    assert [c["name"] for c in preview["columns"]] == ["name", "value"]
    assert preview["row_count"] == 3

    result = run_query(conn, "SELECT sum(value) AS total FROM data")
    assert result["columns"] == ["total"]
    assert result["rows"] == [[6]]


def test_xlsx_preview(tmp_path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "value"])
    ws.append(["a", 1])
    ws.append(["b", 2])
    path = tmp_path / "test.xlsx"
    wb.save(path)

    conn = load_table(str(path), "xlsx")
    preview = schema_preview(conn)
    assert preview["row_count"] == 2


def test_export_csv(tmp_path) -> None:
    path = tmp_path / "test.csv"
    path.write_text("name,value\na,1\n")
    conn = load_table(str(path), "csv")
    csv_text = export_csv(conn, "SELECT * FROM data")
    assert "name,value" in csv_text
    assert "a,1" in csv_text
