import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import sqlite3

def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    ).hex()
    return hashed, salt

def verify_password(password: str, password_hash: str, salt: str) -> bool:
    hashed, _ = hash_password(password, salt)
    return hmac.compare_digest(hashed, password_hash)

def init_auth_tables(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL COLLATE NOCASE,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'viewer',
        created_at TEXT NOT NULL
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);")
    conn.commit()

def seed_default_users(conn: sqlite3.Connection):
    """Garante a existência e credenciais atualizadas dos usuários padrão."""
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    default_users = [
        {
            "username": "breno.zocatelli",
            "display_name": "Breno Zocatelli",
            "password": "Zocadio171964!",
            "role": "admin"
        },
        {
            "username": "Milcopias",
            "display_name": "Milcópias",
            "password": "mil@2015",
            "role": "viewer"
        }
    ]

    for u in default_users:
        cursor.execute("SELECT id FROM users WHERE username = ?", (u["username"],))
        row = cursor.fetchone()
        pw_hash, salt = hash_password(u["password"])
        if not row:
            cursor.execute("""
            INSERT INTO users (username, display_name, password_hash, salt, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (u["username"], u["display_name"], pw_hash, salt, u["role"], now))
        else:
            # Atualiza senha e role para garantir sincronia com os requisitos do usuário
            cursor.execute("""
            UPDATE users SET display_name = ?, password_hash = ?, salt = ?, role = ?
            WHERE id = ?
            """, (u["display_name"], pw_hash, salt, u["role"], row[0]))

    conn.commit()

def authenticate_user(conn: sqlite3.Connection, username: str, password: str) -> Optional[Dict[str, Any]]:
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, username, display_name, password_hash, salt, role
    FROM users
    WHERE username = ?
    """, (username.strip(),))
    row = cursor.fetchone()
    if not row:
        return None

    user_dict = dict(row)
    if verify_password(password, user_dict["password_hash"], user_dict["salt"]):
        return {
            "id": user_dict["id"],
            "username": user_dict["username"],
            "display_name": user_dict["display_name"],
            "role": user_dict["role"]
        }
    return None

def create_session(conn: sqlite3.Connection, user_id: int, days_valid: int = 30) -> str:
    cursor = conn.cursor()
    token = secrets.token_urlsafe(36)
    created_at = datetime.now()
    expires_at = created_at + timedelta(days=days_valid)

    cursor.execute("""
    INSERT INTO sessions (token, user_id, created_at, expires_at)
    VALUES (?, ?, ?, ?)
    """, (token, user_id, created_at.isoformat(), expires_at.isoformat()))
    conn.commit()
    return token

def get_user_by_session(conn: sqlite3.Connection, token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
    SELECT u.id, u.username, u.display_name, u.role, s.expires_at
    FROM sessions s
    JOIN users u ON s.user_id = u.id
    WHERE s.token = ? AND s.expires_at > ?
    """, (token, now))
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"]
    }

def delete_session(conn: sqlite3.Connection, token: str):
    if not token:
        return
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
