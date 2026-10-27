import sqlite3
import os
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

from . import auth

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DB_DIR, "knowledge.db")
MD_EXPORT_DIR = os.path.join(DB_DIR, "procedimentos")

os.makedirs(DB_DIR, exist_ok=True)
os.makedirs(MD_EXPORT_DIR, exist_ok=True)

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Tabela principal de procedimentos
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS procedures (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        equipment TEXT NOT NULL,
        category TEXT NOT NULL,
        tags TEXT DEFAULT '',
        summary TEXT DEFAULT '',
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # Tabela de configurações locais (ex: API key do Gemini)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)

    # Tabela virtual FTS5 para busca rápida e inteligente de texto completo
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS procedures_fts USING fts5(
        title,
        equipment,
        category,
        tags,
        summary,
        content,
        content=procedures,
        content_rowid=id
    );
    """)

    # Triggers para sincronizar procedures com procedures_fts
    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS procedures_ai AFTER INSERT ON procedures BEGIN
        INSERT INTO procedures_fts(rowid, title, equipment, category, tags, summary, content)
        VALUES (new.id, new.title, new.equipment, new.category, new.tags, new.summary, new.content);
    END;
    """)

    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS procedures_ad AFTER DELETE ON procedures BEGIN
        INSERT INTO procedures_fts(procedures_fts, rowid, title, equipment, category, tags, summary, content)
        VALUES('delete', old.id, old.title, old.equipment, old.category, old.tags, old.summary, old.content);
    END;
    """)

    cursor.execute("""
    CREATE TRIGGER IF NOT EXISTS procedures_au AFTER UPDATE ON procedures BEGIN
        INSERT INTO procedures_fts(procedures_fts, rowid, title, equipment, category, tags, summary, content)
        VALUES('delete', old.id, old.title, old.equipment, old.category, old.tags, old.summary, old.content);
        INSERT INTO procedures_fts(rowid, title, equipment, category, tags, summary, content)
        VALUES (new.id, new.title, new.equipment, new.category, new.tags, new.summary, new.content);
    END;
    """)

    conn.commit()

    # Inicializa tabelas de usuários e sessões
    auth.init_auth_tables(conn)
    auth.seed_default_users(conn)

    conn.close()

def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).replace(" ", "_").strip()

def export_to_markdown(proc: Dict[str, Any]):
    """Exporta o procedimento para arquivo .md legível na pasta data/procedimentos"""
    try:
        cat_dir = os.path.join(MD_EXPORT_DIR, _sanitize_filename(proc["category"]))
        os.makedirs(cat_dir, exist_ok=True)
        filename = f"{_sanitize_filename(proc['equipment'])}_{_sanitize_filename(proc['title'])}.md"
        filepath = os.path.join(cat_dir, filename)

        md_content = f"""# {proc['title']}
- **Equipamento/Sistema:** {proc['equipment']}
- **Categoria:** {proc['category']}
- **Tags:** {proc['tags']}
- **Atualizado em:** {proc['updated_at']}

## Resumo
{proc['summary']}

---

## Conteúdo Completo
{proc['content']}
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)
    except Exception as e:
        print(f"Erro ao exportar markdown: {e}")

def save_procedure(
    title: str,
    equipment: str,
    category: str,
    tags: str,
    summary: str,
    content: str,
    proc_id: Optional[int] = None
) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if proc_id:
        cursor.execute("""
        UPDATE procedures
        SET title = ?, equipment = ?, category = ?, tags = ?, summary = ?, content = ?, updated_at = ?
        WHERE id = ?
        """, (title.strip(), equipment.strip(), category.strip(), tags.strip(), summary.strip(), content.strip(), now, proc_id))
        result_id = proc_id
    else:
        cursor.execute("""
        INSERT INTO procedures (title, equipment, category, tags, summary, content, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (title.strip(), equipment.strip(), category.strip(), tags.strip(), summary.strip(), content.strip(), now, now))
        result_id = cursor.lastrowid

    conn.commit()
    conn.close()

    # Atualiza exportação .md
    export_to_markdown({
        "id": result_id,
        "title": title,
        "equipment": equipment,
        "category": category,
        "tags": tags,
        "summary": summary,
        "content": content,
        "updated_at": now
    })

    return result_id

def get_procedure(proc_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM procedures WHERE id = ?", (proc_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def list_procedures(category: Optional[str] = None, equipment: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT id, title, equipment, category, tags, summary, updated_at FROM procedures WHERE 1=1"
    params = []

    if category:
        query += " AND category = ?"
        params.append(category)
    if equipment:
        query += " AND equipment = ?"
        params.append(equipment)

    query += " ORDER BY updated_at DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def search_procedures(query: str, limit: int = 15) -> List[Dict[str, Any]]:
    """
    Busca semântica e full-text com ranking BM25 e tolerância a termos soltos.
    """
    if not query or not query.strip():
        return list_procedures()[:limit]

    conn = get_connection()
    cursor = conn.cursor()
    clean_query = query.strip()

    # Prepara consulta FTS: quebra em palavras para permitir busca OR e prefixos *
    terms = re.findall(r'\w+', clean_query, re.UNICODE)
    if not terms:
        return []

    # Cria consulta FTS com prefixos para auto-completar termos (ex: "fusor*" OR "reset*")
    fts_match_query = " OR ".join([f'"{t}"*' for t in terms])

    try:
        # Busca com ranking BM25 nativo do FTS5
        sql = """
        SELECT 
            p.id, p.title, p.equipment, p.category, p.tags, p.summary, p.updated_at,
            snippet(procedures_fts, 5, '<mark class="bg-yellow-200 dark:bg-yellow-800 text-yellow-900 dark:text-yellow-100 font-semibold px-1 rounded">', '</mark>', '...', 25) as snippet,
            bm25(procedures_fts, 5.0, 4.0, 3.0, 3.0, 2.0, 1.0) as rank
        FROM procedures_fts
        JOIN procedures p ON p.id = procedures_fts.rowid
        WHERE procedures_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """
        cursor.execute(sql, (fts_match_query, limit))
        rows = cursor.fetchall()
        results = [dict(r) for r in rows]
    except Exception:
        # Fallback para busca LIKE padrão caso haja erro na sintaxe FTS
        like_pattern = f"%{clean_query}%"
        sql = """
        SELECT id, title, equipment, category, tags, summary, updated_at, summary as snippet, 0 as rank
        FROM procedures
        WHERE title LIKE ? OR equipment LIKE ? OR tags LIKE ? OR content LIKE ? OR summary LIKE ?
        ORDER BY updated_at DESC
        LIMIT ?
        """
        cursor.execute(sql, (like_pattern, like_pattern, like_pattern, like_pattern, like_pattern, limit))
        results = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return results

def delete_procedure(proc_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM procedures WHERE id = ?", (proc_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

def get_stats() -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as total FROM procedures")
    total = cursor.fetchone()["total"]

    cursor.execute("SELECT DISTINCT category FROM procedures ORDER BY category")
    categories = [r["category"] for r in cursor.fetchall()]

    cursor.execute("SELECT DISTINCT equipment FROM procedures ORDER BY equipment")
    equipments = [r["equipment"] for r in cursor.fetchall()]

    conn.close()
    return {
        "total": total,
        "categories": categories,
        "equipments": equipments
    }

def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO settings (key, value) VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, value))
    conn.commit()
    conn.close()

def remove_sample_procedures_if_present():
    """Remove os 3 procedimentos de exemplo para garantir que o banco fique limpo."""
    conn = get_connection()
    cursor = conn.cursor()
    sample_titles = [
        "Reset de Fusor e Limpeza de Código de Erro SC542",
        "Emissão de Requisição de Suprimento (Operação 02)",
        "Ajuste Manual de Ponto e Inclusão de Atestado Médico"
    ]
    for title in sample_titles:
        cursor.execute("SELECT id FROM procedures WHERE title = ?", (title,))
        row = cursor.fetchone()
        if row:
            proc_id = row["id"]
            cursor.execute("DELETE FROM procedures WHERE id = ?", (proc_id,))
    conn.commit()
    conn.close()
