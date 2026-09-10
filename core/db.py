import os
import sqlite3
from contextlib import contextmanager
from core.config import Config

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def get_db_path():
    db_name = Config.DB_NAME
    if db_name == ':memory:' or os.path.isabs(db_name):
        return db_name
    return os.path.join(BASE_DIR, db_name)

@contextmanager
def get_db_connection():
    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    conn = None
    try:
        if engine in ('postgres', 'postgresql'):
            import psycopg
            from psycopg.rows import dict_row
            conn = psycopg.connect(
                host=Config.DB_HOST,
                port=Config.DB_PORT,
                dbname=Config.DB_NAME,
                user=Config.DB_USER,
                password=Config.DB_PASSWORD,
                row_factory=dict_row
            )
        else:
            db_path = get_db_path()
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row

        yield conn
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

def execute_sql(conn, sql: str, params: tuple = ()):
    engine = getattr(Config, 'DB_ENGINE', 'sqlite').lower()
    if engine in ('postgres', 'postgresql'):
        sql = sql.replace('?', '%s')
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur

def init_db():
    with get_db_connection() as conn:
        execute_sql(conn, '''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        ''')
