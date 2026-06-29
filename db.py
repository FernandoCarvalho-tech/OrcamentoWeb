import os
import psycopg2
import psycopg2.extras
from werkzeug.security import generate_password_hash

DATABASE_URL = os.environ.get("DATABASE_URL")


class _PGCursor:
    """Wraps a psycopg2 cursor to expose sqlite3-style .lastrowid."""

    def __init__(self, cursor, lastrowid=None):
        self._cursor = cursor
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class _PGConnection:
    """Wraps a psycopg2 connection to expose a sqlite3-style .execute() API
    (using '?' placeholders and dict-like rows) so the rest of the app can stay unchanged."""

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, query, params=()):
        pg_query = query.replace("?", "%s")
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        is_insert = pg_query.strip().upper().startswith("INSERT")
        if is_insert and "RETURNING" not in pg_query.upper():
            pg_query += " RETURNING id"
        cur.execute(pg_query, params)
        lastrowid = None
        if is_insert:
            row = cur.fetchone()
            lastrowid = row["id"] if row else None
        return _PGCursor(cur, lastrowid)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_conn():
    raw_conn = psycopg2.connect(DATABASE_URL)
    return _PGConnection(raw_conn)


def init_db():
    conn = get_conn()
    cur = conn._conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS empresa (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            nome TEXT,
            cnpj TEXT,
            endereco TEXT,
            telefone TEXT,
            email TEXT,
            logo_path TEXT,
            smtp_servidor TEXT,
            smtp_porta INTEGER,
            smtp_usuario TEXT,
            smtp_senha TEXT
        )
    """)
    cur.execute("INSERT INTO empresa (id) VALUES (1) ON CONFLICT (id) DO NOTHING")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS login_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            usuario TEXT NOT NULL,
            senha_hash TEXT NOT NULL
        )
    """)
    cur.execute("SELECT 1 FROM login_config WHERE id = 1")
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO login_config (id, usuario, senha_hash) VALUES (1, %s, %s)",
            ("admin", generate_password_hash("admin123")),
        )

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            documento TEXT,
            endereco TEXT,
            telefone TEXT,
            email TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            id SERIAL PRIMARY KEY,
            descricao TEXT NOT NULL,
            unidade TEXT DEFAULT 'un',
            preco_unitario REAL NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mao_de_obra (
            id SERIAL PRIMARY KEY,
            descricao TEXT NOT NULL,
            unidade TEXT DEFAULT 'h',
            valor_unitario REAL NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orcamentos (
            id SERIAL PRIMARY KEY,
            cliente_id INTEGER NOT NULL REFERENCES clientes (id),
            data TEXT NOT NULL,
            validade_dias INTEGER DEFAULT 15,
            observacoes TEXT,
            total REAL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orcamento_itens (
            id SERIAL PRIMARY KEY,
            orcamento_id INTEGER NOT NULL REFERENCES orcamentos (id),
            tipo TEXT NOT NULL CHECK (tipo IN ('produto', 'mao_de_obra')),
            descricao TEXT NOT NULL,
            unidade TEXT,
            quantidade REAL NOT NULL DEFAULT 1,
            valor_unitario REAL NOT NULL DEFAULT 0,
            valor_total REAL NOT NULL DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()
