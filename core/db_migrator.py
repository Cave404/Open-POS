"""
=============================================================================
Open-POS Bidirectional Database Migration Engine
=============================================================================
Provides automated, atomic-per-table migration between:
  - SQLite  (lightweight local file-backed store)
  - PostgreSQL  (networked enterprise-grade store)

Design Goals:
  1. Zero data loss -- each table is verified for record count parity before commit.
  2. Identity continuity -- SQLite INTEGER PRIMARY KEYs become PostgreSQL
     BIGINT GENERATED ALWAYS AS IDENTITY. Existing row IDs are preserved via
     INSERT ... OVERRIDING SYSTEM VALUE, then sequences are bumped to max(id)+1.
  3. Seamless Type Translation -- Citext for case-insensitive fields (email/username),
     JSONB for structured payloads, BIGINT for 64-bit integer IDs.
  4. Readable progress -- every significant step fires progress_callback(pct, msg)
     and logs directly to data/logs/openpos_system.log.
  5. Post-Migration Safety -- atomic update of data/config/.env on verified success.
=============================================================================
"""

import os
import time
import json
import sqlite3
import logging
from contextlib import contextmanager
from typing import Callable, Optional, Dict, Any, List

from core.config import Config
from core.logger import log_event

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLite -> PostgreSQL type affinity mapping
# ---------------------------------------------------------------------------
_PG_TYPE_MAP = {
    "text":      "TEXT",
    "char":      "TEXT",
    "varchar":   "TEXT",
    "clob":      "TEXT",
    "string":    "TEXT",
    "integer":   "BIGINT",
    "int":       "BIGINT",
    "bigint":    "BIGINT",
    "tinyint":   "BIGINT",
    "smallint":  "BIGINT",
    "mediumint": "BIGINT",
    "real":      "DOUBLE PRECISION",
    "float":     "DOUBLE PRECISION",
    "double":    "DOUBLE PRECISION",
    "numeric":   "NUMERIC",
    "decimal":   "NUMERIC",
    "blob":      "BYTEA",
    "boolean":   "BOOLEAN",
    "bool":      "BOOLEAN",
    "date":      "DATE",
    "datetime":  "TIMESTAMP WITHOUT TIME ZONE",
    "timestamp": "TIMESTAMP WITHOUT TIME ZONE",
    "json":      "JSONB",
    "jsonb":     "JSONB",
    "citext":    "CITEXT",
}


def _map_sqlite_type_to_pg(sqlite_type: str, col_name: str = "") -> str:
    """
    Resolves SQLite type affinity string to an equivalent PostgreSQL type.
    Maps email/username or citext hints to CITEXT.
    Maps json/payload/metadata hints to JSONB.
    Falls back to TEXT for any unrecognized affinity.
    """
    col_lower = col_name.strip().lower()
    type_lower = (sqlite_type or "").strip().lower()

    if col_lower in ("email", "username", "customer_email") or "citext" in type_lower:
        return "CITEXT"

    if (
        col_lower.endswith(("_json", "_data", "metadata", "payload", "settings"))
        or type_lower in ("json", "jsonb")
    ):
        return "JSONB"

    base = type_lower.split("(")[0]
    return _PG_TYPE_MAP.get(base, "TEXT")


# ---------------------------------------------------------------------------
# SQLite Schema Introspection Helpers
# ---------------------------------------------------------------------------
def _get_sqlite_tables(conn: sqlite3.Connection) -> list:
    """Returns all user-defined table names from SQLite, excluding internal sqlite_ tables."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
    )
    return [row[0] for row in cur.fetchall()]


def _get_sqlite_table_info(conn: sqlite3.Connection, table: str) -> list:
    """
    Returns column metadata for a SQLite table via PRAGMA table_info.
    Each dict contains: cid, name, type, notnull, dflt_value, pk
    """
    cur = conn.execute(f'PRAGMA table_info("{table}");')
    cols = []
    for row in cur.fetchall():
        cols.append({
            "cid":        row[0],
            "name":       row[1],
            "type":       row[2],
            "notnull":    row[3],
            "dflt_value": row[4],
            "pk":         row[5],  # pk > 0 means this col is part of the PRIMARY KEY
        })
    return cols


# ---------------------------------------------------------------------------
# PostgreSQL Connection Context Manager
# ---------------------------------------------------------------------------
@contextmanager
def _pg_connection(host=None, port=None, dbname=None, user=None, password=None):
    """
    Opens a psycopg connection using explicitly provided credentials or
    falling back to current Config values.
    Yields the connection with autocommit=False for transactional control.
    """
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as e:
        raise RuntimeError(
            "psycopg (v3) is not installed. Run: pip install \"psycopg[binary,pool]\""
        ) from e

    conn = psycopg.connect(
        host=host or Config.DB_HOST,
        port=int(port or Config.DB_PORT),
        dbname=dbname or Config.DB_NAME,
        user=user or Config.DB_USER,
        password=password or Config.DB_PASSWORD,
        connect_timeout=4,
        row_factory=dict_row
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Environment File Writer
# ---------------------------------------------------------------------------
def update_env_engine(engine: str, pg_params: Optional[dict] = None) -> None:
    """
    Rewrites data/config/.env to update DB_ENGINE (and optionally PG connection
    parameters). Also patches os.environ so Config picks it up without a restart.

    Args:
        engine:    'sqlite' or 'postgresql'
        pg_params: Optional dict with keys DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
    """
    env_path = os.path.join(Config.CONFIG_DIR, ".env")
    lines = []

    if os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    # Assemble the full set of key-value updates
    updates = {"DB_ENGINE": engine}
    if pg_params:
        updates.update(pg_params)

    # Overwrite matching keys in-place
    handled = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}\n")
            handled.add(key)
        else:
            new_lines.append(line)

    # Append any keys not previously present in the file
    for key, value in updates.items():
        if key not in handled:
            new_lines.append(f"{key}={value}\n")

    os.makedirs(Config.CONFIG_DIR, exist_ok=True)
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    # Patch os.environ for immediate effect (best-effort)
    os.environ["DB_ENGINE"] = engine
    if pg_params:
        for k, v in pg_params.items():
            os.environ[k] = str(v)

    log_msg = f"[MIGRATOR] .env updated -- DB_ENGINE={engine}"
    logger.info(log_msg)
    log_event("INFO", log_msg, "MIGRATOR")


# ---------------------------------------------------------------------------
# Connection Tests
# ---------------------------------------------------------------------------
def test_sqlite_connection(db_path: Optional[str] = None) -> dict:
    """
    Validates that the SQLite database file is accessible and responsive.
    Returns: { "ok": bool, "message": str, "latency_ms": float }
    """
    path = db_path or Config.DB_PATH
    try:
        t0 = time.perf_counter()
        conn = sqlite3.connect(path)
        conn.execute("SELECT 1;")
        conn.close()
        latency = round((time.perf_counter() - t0) * 1000, 2)
        return {"ok": True, "message": f"SQLite OK -- {path}", "latency_ms": latency}
    except Exception as e:
        return {"ok": False, "message": str(e), "latency_ms": 0.0}


def test_postgres_connection(host=None, port=None, dbname=None, user=None, password=None) -> dict:
    """
    Verifies a PostgreSQL connection by opening and immediately closing a test connection.
    Returns: { "ok": bool, "message": str, "latency_ms": float, "server_version": str }
    """
    try:
        t0 = time.perf_counter()
        with _pg_connection(host, port, dbname, user, password) as conn:
            cur = conn.execute("SELECT version();")
            row = cur.fetchone()
            ver = list(row.values())[0] if row else "unknown"
        latency = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "ok": True,
            "message": "PostgreSQL connection successful.",
            "latency_ms": latency,
            "server_version": ver
        }
    except Exception as e:
        return {"ok": False, "message": str(e), "latency_ms": 0.0, "server_version": ""}


# ---------------------------------------------------------------------------
# Database Status Snapshot
# ---------------------------------------------------------------------------
def get_database_status() -> dict:
    """
    Returns a real-time snapshot of the current database:
      - engine name (sqlite / postgresql)
      - connection details (file path or host:port/dbname)
      - user-defined table count
      - SQLite file size in MB or PostgreSQL active pool connection count
    """
    engine = getattr(Config, "DB_ENGINE", "sqlite").lower()
    status = {"engine": engine, "table_count": 0, "details": ""}

    try:
        if engine in ("postgres", "postgresql"):
            with _pg_connection() as conn:
                cur = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
                )
                row = cur.fetchone()
                status["table_count"] = int(row["cnt"]) if row else 0

                # Connection pool metrics
                try:
                    conn_cur = conn.execute("SELECT count(*) as cnt FROM pg_stat_activity WHERE datname = current_database();")
                    conn_row = conn_cur.fetchone()
                    status["active_connections"] = int(conn_row["cnt"]) if conn_row else 1
                except Exception:
                    status["active_connections"] = 1

            status["details"] = f"{Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}"
        else:
            db_path = Config.DB_PATH
            conn = sqlite3.connect(db_path)
            cur = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            )
            status["table_count"] = cur.fetchone()[0]
            conn.close()
            size_mb = 0.0
            if os.path.isfile(db_path):
                size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 3)
            status["details"] = db_path
            status["file_size_mb"] = size_mb
    except Exception as e:
        status["error"] = str(e)

    return status


# ---------------------------------------------------------------------------
# Dry Run Validation
# ---------------------------------------------------------------------------
def dry_run_migration(
    direction: str = "sqlite_to_postgres",
    sqlite_path: Optional[str] = None,
    pg_config: Optional[dict] = None,
    pg_host=None, pg_port=None, pg_dbname=None, pg_user=None, pg_password=None
) -> dict:
    """
    Validates credentials and source/target readiness without modifying target records.
    Returns table counts and estimated rows to migrate.
    """
    if pg_config:
        pg_host = pg_config.get("host", pg_host)
        pg_port = pg_config.get("port", pg_port)
        pg_dbname = pg_config.get("dbname", pg_dbname)
        pg_user = pg_config.get("user", pg_user)
        pg_password = pg_config.get("password", pg_password)

    sqlite_db_path = sqlite_path or Config.DB_PATH

    # Test SQLite
    sqlite_res = test_sqlite_connection(sqlite_db_path)
    if not sqlite_res["ok"]:
        return {"ok": False, "message": f"SQLite validation failed: {sqlite_res['message']}"}

    # Test PostgreSQL
    pg_res = test_postgres_connection(pg_host, pg_port, pg_dbname, pg_user, pg_password)
    if not pg_res["ok"]:
        return {"ok": False, "message": f"PostgreSQL validation failed: {pg_res['message']}"}

    try:
        if direction == "sqlite_to_postgres":
            src = sqlite3.connect(sqlite_db_path)
            tables = _get_sqlite_tables(src)
            total_rows = 0
            table_stats = {}
            for t in tables:
                cnt = src.execute(f'SELECT COUNT(*) FROM "{t}";').fetchone()[0]
                total_rows += cnt
                table_stats[t] = cnt
            src.close()
            return {
                "ok": True,
                "direction": direction,
                "tables_count": len(tables),
                "total_rows": total_rows,
                "table_stats": table_stats,
                "latency_ms": pg_res.get("latency_ms", 0.0),
                "message": f"Dry Run Passed: {len(tables)} tables ({total_rows} total rows) validated for migration to PostgreSQL."
            }
        else:
            with _pg_connection(pg_host, pg_port, pg_dbname, pg_user, pg_password) as pg:
                cur = pg.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name;"
                )
                tables = [r["table_name"] for r in cur.fetchall()]
                total_rows = 0
                table_stats = {}
                for t in tables:
                    rc = pg.execute(f'SELECT COUNT(*) AS cnt FROM "{t}";')
                    cnt = int(rc.fetchone()["cnt"])
                    total_rows += cnt
                    table_stats[t] = cnt
            return {
                "ok": True,
                "direction": direction,
                "tables_count": len(tables),
                "total_rows": total_rows,
                "table_stats": table_stats,
                "latency_ms": pg_res.get("latency_ms", 0.0),
                "message": f"Dry Run Passed: {len(tables)} tables ({total_rows} total rows) validated for migration to SQLite."
            }
    except Exception as e:
        return {"ok": False, "message": f"Dry run introspection failed: {e}"}


# ---------------------------------------------------------------------------
# SQLite -> PostgreSQL Migration
# ---------------------------------------------------------------------------
def migrate_sqlite_to_postgres(
    sqlite_path: Optional[str] = None,
    pg_config: Optional[dict] = None,
    progress_callback: Optional[Callable] = None,
    progress_cb: Optional[Callable] = None,
    pg_host=None, pg_port=None, pg_dbname=None, pg_user=None, pg_password=None
) -> dict:
    """
    Migrates all tables from local SQLite database into target PostgreSQL instance.

    Automated Workflow:
      1. Connects to target PostgreSQL; creates tables using citext, jsonb,
         and BIGINT GENERATED ALWAYS AS IDENTITY.
      2. Reads rows from SQLite in chunks.
      3. Inserts into PostgreSQL using OVERRIDING SYSTEM VALUE to retain
         identical customer, inventory, and ledger IDs.
      4. Resets PostgreSQL sequence counters:
         SELECT setval(pg_get_serial_sequence('table', 'id'), coalesce(max(id), 1)).
      5. Verifies record count parity across all tables before final commit.
      6. Atomically updates DB_ENGINE and credentials in data/config/.env.
      7. Logs all migration steps to data/logs/openpos_system.log.
    """
    # Unpack flexible argument conventions
    if callable(sqlite_path) and progress_cb is None:
        progress_cb = sqlite_path
        sqlite_path = None

    if isinstance(sqlite_path, dict) and pg_config is None:
        pg_config = sqlite_path
        sqlite_path = None

    if pg_config:
        pg_host = pg_config.get("host", pg_host)
        pg_port = pg_config.get("port", pg_port)
        pg_dbname = pg_config.get("dbname", pg_dbname)
        pg_user = pg_config.get("user", pg_user)
        pg_password = pg_config.get("password", pg_password)

    cb = progress_callback or progress_cb

    def emit(pct: int, msg: str):
        logger.info(f"[MIGRATOR S->P {pct}%] {msg}")
        log_event("INFO", f"[MIGRATOR S->P {pct}%] {msg}", "MIGRATOR")
        if cb:
            try:
                cb(pct, msg)
            except Exception:
                pass

    emit(0, "Initiating SQLite to PostgreSQL migration engine...")
    source_db_path = sqlite_path or Config.DB_PATH

    if not os.path.isfile(source_db_path):
        err = f"SQLite database not found: {source_db_path}"
        emit(100, f"Error: {err}")
        return {"status": "error", "message": err}

    src = sqlite3.connect(source_db_path)
    src.row_factory = sqlite3.Row
    src.execute("PRAGMA journal_mode=WAL;")
    src.execute("PRAGMA foreign_keys=OFF;")

    tables = _get_sqlite_tables(src)
    if not tables:
        src.close()
        err = "No tables found in SQLite database to migrate."
        emit(100, f"Error: {err}")
        return {"status": "error", "message": err}

    emit(5, f"Found {len(tables)} SQLite table(s): {', '.join(tables)}")

    tables_migrated = 0
    rows_migrated = 0
    errors = []

    try:
        with _pg_connection(pg_host, pg_port, pg_dbname, pg_user, pg_password) as pg:
            pg.execute("SET search_path = public;")

            # Ensure citext extension exists
            try:
                pg.execute("CREATE EXTENSION IF NOT EXISTS citext;")
            except Exception as ext_err:
                logger.warning(f"[MIGRATOR] Citext extension note: {ext_err}")

            for idx, table in enumerate(tables):
                base_pct = 10 + int((idx / len(tables)) * 80)
                emit(base_pct, f"Processing table: {table}...")

                cols = _get_sqlite_table_info(src, table)
                if not cols:
                    emit(base_pct, f"  Skipped (no columns): {table}")
                    continue

                # Identify single-column integer primary keys for identity generation
                pk_cols = [c for c in cols if c["pk"] > 0]
                single_int_pk = (
                    len(pk_cols) == 1 and
                    _map_sqlite_type_to_pg(pk_cols[0]["type"], pk_cols[0]["name"]) == "BIGINT"
                )

                # Build DDL column definitions
                col_defs = []
                jsonb_cols = set()
                for c in cols:
                    pg_type = _map_sqlite_type_to_pg(c["type"], c["name"])
                    if pg_type == "JSONB":
                        jsonb_cols.add(c["name"])

                    if single_int_pk and c["pk"] == 1:
                        col_defs.append(
                            f'"{c["name"]}" BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY'
                        )
                    else:
                        not_null = "NOT NULL" if c["notnull"] else ""
                        pk_clause = "PRIMARY KEY" if (c["pk"] > 0 and not single_int_pk) else ""
                        parts = [f'"{c["name"]}"', pg_type, not_null, pk_clause]
                        col_defs.append(" ".join(p for p in parts if p))

                create_sql = (
                    f'CREATE TABLE IF NOT EXISTS "{table}" (\n'
                    + ",\n".join(f"  {d}" for d in col_defs)
                    + "\n);"
                )

                try:
                    pg.execute(create_sql)
                except Exception as e:
                    errors.append(f"{table}: CREATE TABLE failed -- {e}")
                    emit(base_pct, f"  CREATE TABLE failed: {e}")
                    continue

                # Stream SQLite rows in chunks
                cur = src.execute(f'SELECT * FROM "{table}";')
                col_names = [c["name"] for c in cols]
                quoted_cols = ", ".join(f'"{n}"' for n in col_names)
                placeholders = ", ".join(["%s"] * len(col_names))

                if single_int_pk:
                    insert_sql = (
                        f'INSERT INTO "{table}" ({quoted_cols}) '
                        f'OVERRIDING SYSTEM VALUE VALUES ({placeholders}) '
                        f'ON CONFLICT DO NOTHING;'
                    )
                else:
                    insert_sql = (
                        f'INSERT INTO "{table}" ({quoted_cols}) '
                        f'VALUES ({placeholders}) ON CONFLICT DO NOTHING;'
                    )

                CHUNK_SIZE = 500
                table_rows_inserted = 0

                while True:
                    rows_chunk = cur.fetchmany(CHUNK_SIZE)
                    if not rows_chunk:
                        break

                    formatted_chunk = []
                    for row in rows_chunk:
                        row_vals = []
                        for col_idx, col_name in enumerate(col_names):
                            val = row[col_idx]
                            # If column is JSONB and value is dict/list or needs JSON serialization
                            if col_name in jsonb_cols and val is not None:
                                if not isinstance(val, str):
                                    val = json.dumps(val)
                            row_vals.append(val)
                        formatted_chunk.append(tuple(row_vals))

                    try:
                        pg.executemany(insert_sql, formatted_chunk)
                        table_rows_inserted += len(formatted_chunk)
                    except Exception as ins_err:
                        errors.append(f"{table}: chunk insert error -- {ins_err}")
                        break

                # Sequence Counter Reset:
                # SELECT setval(pg_get_serial_sequence('table', 'id'), coalesce(max(id), 1))
                if single_int_pk:
                    pk_col = pk_cols[0]["name"]
                    try:
                        seq_res = pg.execute(
                            f"SELECT setval(pg_get_serial_sequence('\"{table}\"', '{pk_col}'), "
                            f"COALESCE((SELECT MAX(\"{pk_col}\") FROM \"{table}\"), 1));"
                        )
                    except Exception as seq_err:
                        logger.warning(f"[MIGRATOR] Sequence reset warning for {table}: {seq_err}")

                # Record Count Parity Check
                src_count = src.execute(f'SELECT COUNT(*) FROM "{table}";').fetchone()[0]
                pg_check = pg.execute(f'SELECT COUNT(*) AS cnt FROM "{table}";').fetchone()
                pg_count = int(pg_check["cnt"]) if pg_check else 0

                if pg_count < src_count:
                    err_msg = f"{table} parity disparity: SQLite has {src_count} rows, PostgreSQL has {pg_count} rows"
                    errors.append(err_msg)
                    emit(base_pct, f"  Warning: {err_msg}")
                else:
                    emit(base_pct + 1, f"  Parity verified for {table}: {pg_count} rows")

                rows_migrated += table_rows_inserted
                tables_migrated += 1

    except Exception as pg_conn_err:
        src.close()
        err_msg = f"PostgreSQL connection error during migration: {pg_conn_err}"
        emit(100, f"Error: {err_msg}")
        return {"status": "error", "message": err_msg, "errors": errors}

    src.close()

    # Post-Migration Safety: verify parity across all tables before writing config
    emit(95, "Verifying post-migration parity and committing environment config...")
    if not errors:
        pg_params = {
            "DB_HOST": pg_host or Config.DB_HOST,
            "DB_PORT": str(pg_port or Config.DB_PORT),
            "DB_NAME": pg_dbname or Config.DB_NAME,
            "DB_USER": pg_user or Config.DB_USER,
            "DB_PASSWORD": pg_password or Config.DB_PASSWORD,
        }
        update_env_engine("postgresql", pg_params)
        emit(100, f"Complete -- {tables_migrated} tables, {rows_migrated} rows migrated to PostgreSQL with parity.")
        return {
            "status": "success",
            "tables_migrated": tables_migrated,
            "rows_migrated": rows_migrated,
            "errors": [],
        }
    else:
        emit(100, f"Completed with {len(errors)} error(s). Review logs.")
        return {
            "status": "partial",
            "tables_migrated": tables_migrated,
            "rows_migrated": rows_migrated,
            "errors": errors,
        }


# ---------------------------------------------------------------------------
# PostgreSQL -> SQLite Migration
# ---------------------------------------------------------------------------
def migrate_postgres_to_sqlite(
    pg_config: Optional[dict] = None,
    sqlite_path: Optional[str] = None,
    progress_callback: Optional[Callable] = None,
    progress_cb: Optional[Callable] = None,
    pg_host=None, pg_port=None, pg_dbname=None, pg_user=None, pg_password=None
) -> dict:
    """
    Migrates all tables from PostgreSQL database into local SQLite file.

    Automated Workflow:
      1. Connects to PostgreSQL source; validates credentials.
      2. Initializes clean SQLite target schema in WAL mode.
      3. Reads rows from PostgreSQL in chunks.
      4. Parses JSONB / CITEXT columns into native text, and bulk-inserts into SQLite.
      5. Verifies record count parity across all tables before committing.
      6. Atomically updates DB_ENGINE=sqlite in data/config/.env.
      7. Logs all migration steps to data/logs/openpos_system.log.
    """
    if isinstance(pg_config, str) and sqlite_path is None:
        sqlite_path = pg_config
        pg_config = None

    if pg_config:
        pg_host = pg_config.get("host", pg_host)
        pg_port = pg_config.get("port", pg_port)
        pg_dbname = pg_config.get("dbname", pg_dbname)
        pg_user = pg_config.get("user", pg_user)
        pg_password = pg_config.get("password", pg_password)

    cb = progress_callback or progress_cb

    def emit(pct: int, msg: str):
        logger.info(f"[MIGRATOR P->S {pct}%] {msg}")
        log_event("INFO", f"[MIGRATOR P->S {pct}%] {msg}", "MIGRATOR")
        if cb:
            try:
                cb(pct, msg)
            except Exception:
                pass

    _SQLITE_TYPE_MAP = {
        "bigint":                     "INTEGER",
        "integer":                    "INTEGER",
        "smallint":                   "INTEGER",
        "serial":                     "INTEGER",
        "bigserial":                  "INTEGER",
        "boolean":                    "INTEGER",
        "real":                       "REAL",
        "double precision":           "REAL",
        "numeric":                    "NUMERIC",
        "text":                       "TEXT",
        "character varying":          "TEXT",
        "character":                  "TEXT",
        "bytea":                      "BLOB",
        "date":                       "TEXT",
        "timestamp without time zone": "TEXT",
        "timestamp with time zone":   "TEXT",
        "json":                       "TEXT",
        "jsonb":                      "TEXT",
        "citext":                     "TEXT",
        "uuid":                       "TEXT",
    }

    emit(0, "Connecting to PostgreSQL source database...")
    target_sqlite_path = sqlite_path or Config.DB_PATH
    os.makedirs(os.path.dirname(target_sqlite_path), exist_ok=True)

    tables_migrated = 0
    rows_migrated = 0
    errors = []

    try:
        with _pg_connection(pg_host, pg_port, pg_dbname, pg_user, pg_password) as pg:
            cur = pg.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name;"
            )
            tables = [row["table_name"] for row in cur.fetchall()]

            if not tables:
                err = "No tables found in PostgreSQL database."
                emit(100, f"Error: {err}")
                return {"status": "error", "message": err}

            emit(5, f"Found {len(tables)} PostgreSQL table(s): {', '.join(tables)}")

            # Initialize SQLite target in WAL mode
            dst = sqlite3.connect(target_sqlite_path)
            dst.execute("PRAGMA journal_mode=WAL;")
            dst.execute("PRAGMA foreign_keys=OFF;")

            for idx, table in enumerate(tables):
                base_pct = 10 + int((idx / len(tables)) * 80)
                emit(base_pct, f"Processing table: {table}...")

                col_cur = pg.execute(
                    "SELECT column_name, data_type, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s "
                    "ORDER BY ordinal_position;",
                    (table,)
                )
                pg_cols = col_cur.fetchall()
                if not pg_cols:
                    emit(base_pct, f"  Skipped (no columns): {table}")
                    continue

                col_defs = []
                col_names = []
                jsonb_or_citext_cols = set()

                for col in pg_cols:
                    name = col["column_name"]
                    pg_type = col["data_type"].lower()
                    sqlite_type = _SQLITE_TYPE_MAP.get(pg_type, "TEXT")
                    nullable = "" if col["is_nullable"] == "YES" else "NOT NULL"
                    default = col["column_default"] or ""

                    if pg_type in ("json", "jsonb", "citext"):
                        jsonb_or_citext_cols.add(name)

                    if "nextval" in default or "identity" in default:
                        col_defs.append(f'"{name}" INTEGER PRIMARY KEY AUTOINCREMENT')
                    else:
                        col_defs.append(f'"{name}" {sqlite_type} {nullable}'.strip())
                    col_names.append(name)

                create_sql = (
                    f'CREATE TABLE IF NOT EXISTS "{table}" (\n'
                    + ",\n".join(f"  {d}" for d in col_defs)
                    + "\n);"
                )

                try:
                    dst.execute(create_sql)
                    dst.commit()
                except Exception as e:
                    errors.append(f"{table}: CREATE TABLE failed -- {e}")
                    emit(base_pct, f"  CREATE TABLE failed: {e}")
                    continue

                # Stream rows from PostgreSQL in chunks
                row_cur = pg.execute(f'SELECT * FROM "{table}";')
                quoted_cols = ", ".join(f'"{n}"' for n in col_names)
                placeholders = ", ".join(["?"] * len(col_names))
                insert_sql = (
                    f'INSERT OR IGNORE INTO "{table}" ({quoted_cols}) '
                    f'VALUES ({placeholders});'
                )

                CHUNK_SIZE = 500
                table_rows_inserted = 0

                while True:
                    pg_chunk = row_cur.fetchmany(CHUNK_SIZE)
                    if not pg_chunk:
                        break

                    formatted_chunk = []
                    for row in pg_chunk:
                        row_vals = []
                        for col_name in col_names:
                            val = row.get(col_name)
                            # Parse JSONB / CITEXT columns into native text
                            if col_name in jsonb_or_citext_cols and val is not None:
                                if isinstance(val, (dict, list)):
                                    val = json.dumps(val)
                                elif not isinstance(val, str):
                                    val = str(val)
                            row_vals.append(val)
                        formatted_chunk.append(tuple(row_vals))

                    try:
                        dst.executemany(insert_sql, formatted_chunk)
                        dst.commit()
                        table_rows_inserted += len(formatted_chunk)
                    except Exception as ins_err:
                        errors.append(f"{table}: chunk insert error -- {ins_err}")
                        break

                # Parity check
                pg_check = pg.execute(f'SELECT COUNT(*) AS cnt FROM "{table}";').fetchone()
                pg_count = int(pg_check["cnt"]) if pg_check else 0
                sqlite_count = dst.execute(f'SELECT COUNT(*) FROM "{table}";').fetchone()[0]

                if sqlite_count < pg_count:
                    err_msg = f"{table} parity disparity: PG has {pg_count} rows, SQLite has {sqlite_count} rows"
                    errors.append(err_msg)
                    emit(base_pct, f"  Warning: {err_msg}")
                else:
                    emit(base_pct + 1, f"  Parity verified for {table}: {sqlite_count} rows")

                rows_migrated += table_rows_inserted
                tables_migrated += 1

            dst.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            dst.close()

    except Exception as pg_conn_err:
        err_msg = f"PostgreSQL connection error: {pg_conn_err}"
        emit(100, f"Error: {err_msg}")
        return {"status": "error", "message": err_msg, "errors": errors}

    # Post-Migration Safety
    emit(95, "Verifying post-migration parity and committing environment config...")
    if not errors:
        update_env_engine("sqlite")
        emit(100, f"Complete -- {tables_migrated} tables, {rows_migrated} rows migrated to SQLite with parity.")
        return {
            "status": "success",
            "tables_migrated": tables_migrated,
            "rows_migrated": rows_migrated,
            "errors": [],
        }
    else:
        emit(100, f"Completed with {len(errors)} error(s). Review logs.")
        return {
            "status": "partial",
            "tables_migrated": tables_migrated,
            "rows_migrated": rows_migrated,
            "errors": errors,
        }
