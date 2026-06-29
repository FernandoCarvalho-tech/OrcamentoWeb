import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "orcamentos.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()

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
    cur.execute("INSERT OR IGNORE INTO empresa (id) VALUES (1)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS login_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            usuario TEXT NOT NULL,
            senha_hash TEXT NOT NULL
        )
    """)
    if not cur.execute("SELECT 1 FROM login_config WHERE id = 1").fetchone():
        from werkzeug.security import generate_password_hash
        cur.execute(
            "INSERT INTO login_config (id, usuario, senha_hash) VALUES (1, ?, ?)",
            ("admin", generate_password_hash("admin123")),
        )

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            documento TEXT,
            endereco TEXT,
            telefone TEXT,
            email TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            unidade TEXT DEFAULT 'un',
            preco_unitario REAL NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS mao_de_obra (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL,
            unidade TEXT DEFAULT 'h',
            valor_unitario REAL NOT NULL DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orcamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            validade_dias INTEGER DEFAULT 15,
            observacoes TEXT,
            total REAL DEFAULT 0,
            FOREIGN KEY (cliente_id) REFERENCES clientes (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orcamento_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orcamento_id INTEGER NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('produto', 'mao_de_obra')),
            descricao TEXT NOT NULL,
            unidade TEXT,
            quantidade REAL NOT NULL DEFAULT 1,
            valor_unitario REAL NOT NULL DEFAULT 0,
            valor_total REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (orcamento_id) REFERENCES orcamentos (id)
        )
    """)

    conn.commit()
    conn.close()
