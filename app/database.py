import sqlite3
import os
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

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

    # Inserir alguns procedimentos de exemplo se a tabela estiver vazia
    cursor.execute("SELECT COUNT(*) as count FROM procedures")
    count = cursor.fetchone()["count"]
    if count == 0:
        _insert_initial_samples(cursor)
        conn.commit()

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

def _insert_initial_samples(cursor):
    """Insere exemplos reais de procedimentos para o usuário já ver o sistema funcionando."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    samples = [
        (
            "Reset de Fusor e Limpeza de Código de Erro SC542",
            "Ricoh Aficio MP 301 / MP 201",
            "Impressoras & Multifuncionais",
            "sc542, fusor, reset, codigo erro, assistencia tecnica, ricoh",
            "Procedimento para limpar código de erro SC542 de aquecimento do fusor após verificação do termostato.",
            """### Descrição do Problema
O código **SC542** ocorre na linha Ricoh quando a unidade fusora não atinge a temperatura operacional no tempo determinado (falha de aquecimento ou desarme do termostato).

### Ferramentas / Pré-requisitos
- Verificar se a lâmpada do fusor e os termistores estão fisicamente íntegros.
- Máquina conectada a tomada com aterramento correto.

### Passo a Passo de Reset no Modo SP (Service Program)
1. Pressione a tecla **Amarela (Clear Mode)**.
2. Digite no teclado numérico: **1 - 0 - 7**.
3. Pressione e segure a tecla **Vermelha (Clear/Stop)** por 5 segundos até o visor mudar.
4. Na tela de toque, selecione **System SP**.
5. No teclado numérico, digite **5 - 8 - 1 - 0** e aperte **#** (ou Enter).
6. Localize o item **SC Reset**.
7. Toque no botão **Execute** na tela.
8. Desligue o interruptor principal da máquina, aguarde 10 segundos e ligue novamente.

> [!WARNING] Atenção
> Nunca faça o reset sem inspecionar visualmente o fusor. Se houver toner acumulado ou termistor danificado, o erro voltará a ocorrer.
""",
            now, now
        ),
        (
            "Emissão de Requisição de Suprimento (Operação 02)",
            "DataBit / DataClassic CRM",
            "Sistemas & ERP",
            "databit, requisicao, suprimento, toner, operacao 02, faturamento",
            "Passo a passo para gerar pedido de remessa de toner e peças pelo DataClassic.",
            """### Objetivo
Lançar no DataBit a saída de toner ou insumos para atendimento de contrato com emissão de nota fiscal ou remessa direta.

### Passo a Passo
1. Acesse o menu **Módulos > Suprimentos > Requisições de Insumos**.
2. Clique no botão **Novo** (ou F2).
3. Selecione o **Código do Cliente / Contrato**:
   - Pressione F9 para pesquisar pela razão social ou CNPJ.
4. No campo **Tipo de Operação**, selecione **02 - Remessa de Suprimento p/ Contrato**.
5. Informe o **Número de Série do Equipamento** (campo obrigatório para controle de rendimento).
6. Na aba **Itens**:
   - Adicione o código do produto (ex: Toner Preto).
   - Insira a quantidade solicitada (atenção à política de no máximo 1 frasco reserva).
   - Registre a contagem atual do medidor informada pelo cliente.
7. Clique em **Gravar e Confirmar**.
8. Imprima a requisição para entrega pelo motoboy/logística.
""",
            now, now
        ),
        (
            "Ajuste Manual de Ponto e Inclusão de Atestado Médico",
            "TopPonto Web",
            "RH & Ponto Eletrônico",
            "topponto, atestado, falta, espelho de ponto, batida, justificativa",
            "Como abonar faltas e registrar atestados no espelho de ponto do colaborador no TopPonto.",
            """### Quando Utilizar
Quando o funcionário esqueceu de registrar a batida ou apresentou atestado médico/declaração de comparecimento.

### Passo a Passo
1. No menu principal do TopPonto, acesse **Cálculos > Cartão Ponto (Espelho)**.
2. Selecione o **Colaborador** e o período desejado.
3. Clique em **Buscar**.
4. Localize a linha referente ao dia da ocorrência:
   - **Caso seja esquecimento de batida:**
     - Dê duplo clique no campo de horário correspondente (Entrada 1, Saída 1, etc.).
     - Digite o horário correto.
     - No campo motivo, selecione *"Esquecimento de registro"*.
   - **Caso seja Atestado Médico (Abono):**
     - Clique na aba **Ocorrências / Afastamentos**.
     - Clique em **Incluir Afastamento**.
     - Selecione o motivo *"Atestado Médico"* e informe as horas ou dias abonados.
5. Clique em **Recalcular** e depois em **Salvar**.
""",
            now, now
        )
    ]

    cursor.executemany("""
    INSERT INTO procedures (title, equipment, category, tags, summary, content, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, samples)
