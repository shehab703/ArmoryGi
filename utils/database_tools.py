from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Dict, List


def sqlite_db_path(database_url: str) -> Path:
    """Resolve SQLite path from SQLAlchemy URL."""
    if not isinstance(database_url, str) or not database_url.startswith("sqlite:///"):
        raise ValueError("Database tools currently support SQLite URLs only.")
    raw_path = database_url.replace("sqlite:///", "", 1).strip()
    if not raw_path or raw_path == ":memory:":
        raise ValueError("In-memory SQLite database is not supported for file operations.")
    return Path(raw_path).resolve(strict=False)


def backup_sqlite(database_url: str, backup_file: str) -> Path:
    """Create a safe backup copy of the active SQLite database."""
    src = sqlite_db_path(database_url)
    dst = Path(backup_file).resolve(strict=False)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def import_sqlite_into_active(database_url: str, source_file: str) -> Path:
    """Import another SQLite DB into the active SQLite file using sqlite backup."""
    src = Path(source_file).resolve(strict=False)
    if not src.exists():
        raise FileNotFoundError(f"Source database not found: {src}")
    dst = sqlite_db_path(database_url)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(src)) as src_conn, sqlite3.connect(str(dst)) as dst_conn:
        src_conn.backup(dst_conn)
    return dst


def export_database(database_url: str, output_file: str, export_format: str) -> Path:
    """
    Export active database in one of: sqlite, sql, json, csv.
    - sqlite: binary copy
    - sql: SQLite dump script
    - json: all user tables with rows
    - csv: weapons table only
    """
    src = sqlite_db_path(database_url)
    out = Path(output_file).resolve(strict=False)
    out.parent.mkdir(parents=True, exist_ok=True)
    fmt = export_format.lower().strip()

    if fmt == "sqlite":
        shutil.copy2(src, out)
        return out

    with sqlite3.connect(str(src)) as conn:
        conn.row_factory = sqlite3.Row

        if fmt == "sql":
            with out.open("w", encoding="utf-8") as f:
                for line in conn.iterdump():
                    f.write(f"{line}\n")
            return out

        if fmt == "json":
            tables = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                AND name NOT LIKE 'sqlite_%'
                AND name != 'weapons_fts'
                AND name NOT LIKE 'weapons_fts_%'
                ORDER BY name
                """
            ).fetchall()
            payload: Dict[str, List[dict]] = {}
            for row in tables:
                table_name = str(row["name"])
                items = conn.execute(f"SELECT * FROM {table_name}").fetchall()
                payload[table_name] = [dict(item) for item in items]
            with out.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            return out

        if fmt == "csv":
            rows = conn.execute("SELECT * FROM weapons ORDER BY id").fetchall()
            headers = [col[1] for col in conn.execute("PRAGMA table_info(weapons)").fetchall()]
            with out.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for row in rows:
                    writer.writerow([row[key] for key in headers])
            return out

    raise ValueError(f"Unsupported export format: {export_format}")
