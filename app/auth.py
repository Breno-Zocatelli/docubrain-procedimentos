import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
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

# ==========================================
# Gestão de Usuários (Painel Administrativo)
# ==========================================

def list_users(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Retorna todos os usuários cadastrados sem expor hash ou salt."""
    cursor = conn.cursor()
    cursor.execute("""
    SELECT id, username, display_name, role, created_at
    FROM users
    ORDER BY id ASC
    """)
    rows = cursor.fetchall()
    return [
        {
            "id": r["id"],
            "username": r["username"],
            "display_name": r["display_name"],
            "role": r["role"],
            "created_at": r["created_at"]
        }
        for r in rows
    ]

def create_user(conn: sqlite3.Connection, username: str, display_name: str, password: str, role: str = "viewer") -> int:
    """Cria um novo usuário com senha criptografada e validação de duplicidade."""
    username = username.strip().lower()
    display_name = display_name.strip()
    password = password.strip()
    
    if not username:
        raise ValueError("O nome de usuário (login) é obrigatório.")
    if len(username) < 3:
        raise ValueError("O nome de usuário deve ter no mínimo 3 caracteres.")
    if not display_name:
        raise ValueError("O nome completo é obrigatório.")
    if not password or len(password) < 4:
        raise ValueError("A senha deve ter no mínimo 4 caracteres.")
    if role not in ("admin", "viewer"):
        role = "viewer"
    
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cursor.fetchone():
        raise ValueError(f"O nome de usuário '{username}' já está em uso.")
    
    pw_hash, salt = hash_password(password)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
    INSERT INTO users (username, display_name, password_hash, salt, role, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (username, display_name, pw_hash, salt, role, now))
    conn.commit()
    return cursor.lastrowid

def update_user(conn: sqlite3.Connection, user_id: int, display_name: Optional[str] = None, role: Optional[str] = None, password: Optional[str] = None):
    """Atualiza dados, permissão e/ou senha de um usuário."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        raise ValueError("Usuário não encontrado.")
    
    # Se estiver tentando rebaixar o role de um admin, verifica se não é o único
    if role and role != "admin" and row["role"] == "admin":
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        admin_count = cursor.fetchone()[0]
        if admin_count <= 1:
            raise ValueError("Não é possível alterar o perfil do único administrador do sistema.")
    
    updates = []
    params = []
    
    if display_name and display_name.strip():
        updates.append("display_name = ?")
        params.append(display_name.strip())
        
    if role and role in ("admin", "viewer"):
        updates.append("role = ?")
        params.append(role)
        
    if password and password.strip():
        if len(password.strip()) < 4:
            raise ValueError("A nova senha deve ter no mínimo 4 caracteres.")
        pw_hash, salt = hash_password(password.strip())
        updates.append("password_hash = ?, salt = ?")
        params.extend([pw_hash, salt])
        
    if updates:
        sql = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
        params.append(user_id)
        cursor.execute(sql, tuple(params))
        conn.commit()

def delete_user(conn: sqlite3.Connection, user_id: int, current_user_id: int):
    """Exclui um usuário e encerra suas sessões ativas."""
    if user_id == current_user_id:
        raise ValueError("Você não pode excluir sua própria conta enquanto estiver conectado.")
    
    cursor = conn.cursor()
    cursor.execute("SELECT username, role FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        raise ValueError("Usuário não encontrado.")
    
    if row["role"] == "admin":
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        admin_count = cursor.fetchone()[0]
        if admin_count <= 1:
            raise ValueError("Não é possível excluir o único administrador do sistema.")
    
    # Remove sessões do usuário excluído e o registro de usuário
    cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
