"""Run a SQL migration file against the configured database.

Usage:
    python scripts/run_migration.py migrations/001_initial_schema.sql
"""
import os
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv
from rich.console import Console

load_dotenv()
console = Console()


def split_sql_statements(sql: str) -> list[str]:
    """Split SQL by ';' respecting comments and strings.

    Lightweight splitter — good enough for our migrations
    (no complex edge cases like semicolons inside strings in our files).
    """
    statements = []
    current = []
    for raw_line in sql.splitlines():
        line = raw_line.strip()
        # skip full-line comments
        if line.startswith("--") or not line:
            continue
        current.append(raw_line)
        if line.rstrip().endswith(";"):
            statement = "\n".join(current).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            current = []
    # any trailing
    if current:
        statement = "\n".join(current).strip().rstrip(";").strip()
        if statement:
            statements.append(statement)
    return statements


def main() -> int:
    if len(sys.argv) < 2:
        console.print("[red]Usage: python scripts/run_migration.py <path-to-sql>[/red]")
        return 1

    sql_path = Path(sys.argv[1])
    if not sql_path.exists():
        console.print(f"[red]File not found: {sql_path}[/red]")
        return 1

    sql_content = sql_path.read_text()
    statements = split_sql_statements(sql_content)
    console.print(f"[cyan]Loaded {len(statements)} statements from {sql_path.name}[/cyan]")

    host = os.getenv("DB_HOST", "127.0.0.1")
    port = int(os.getenv("DB_PORT", "3306"))
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "stock_prediction")

    # ensure database exists
    root_conn = pymysql.connect(host=host, port=port, user=user, password=password, autocommit=True)
    with root_conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS {db_name} "
            f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    root_conn.close()
    console.print(f"[green]✓ Database '{db_name}' ready[/green]")

    # connect to the target DB
    conn = pymysql.connect(
        host=host, port=port, user=user, password=password, database=db_name, autocommit=True
    )
    ok = 0
    failed = 0
    try:
        with conn.cursor() as cur:
            for i, stmt in enumerate(statements, 1):
                first_line = stmt.split("\n", 1)[0][:100]
                try:
                    cur.execute(stmt)
                    ok += 1
                    console.print(f"  [green]✓[/green] [{i:02d}] {first_line}")
                except Exception as e:
                    failed += 1
                    console.print(f"  [red]✗[/red] [{i:02d}] {first_line}")
                    console.print(f"       [red]{e}[/red]")
    finally:
        conn.close()

    console.print(f"\n[bold]Summary:[/bold] {ok} ok, {failed} failed (of {len(statements)})")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
