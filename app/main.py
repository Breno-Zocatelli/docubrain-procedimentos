import os
import markdown
import uuid
from fastapi import FastAPI, HTTPException, Request, Response, Query, UploadFile, File, Form, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List
import subprocess
import threading
import urllib.request
import zipfile
import io
import shutil

from . import database
from . import ai_service
from . import auth

app = FastAPI(title="Base de Procedimentos Operacionais - DocuBrain", version="1.0.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
UPLOADS_DIR = os.path.join(PROJECT_ROOT, "data", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Monta rota de uploads para servir as imagens
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

UPDATE_TOKEN = "mn_docubrain_auto_sync_token_2026"

# Inicializa o banco de dados na inicialização
@app.on_event("startup")
def startup_event():
    database.init_db()
    database.remove_sample_procedures_if_present()
    def _ensure_pypdf():
        try:
            import pypdf
        except ImportError:
            try:
                import sys
                subprocess.run([sys.executable, "-m", "pip", "install", "pypdf"], capture_output=True, timeout=60)
            except Exception:
                pass
    threading.Thread(target=_ensure_pypdf, daemon=True).start()

# Modelos Pydantic
class ProcedureCreate(BaseModel):
    title: str
    equipment: str
    category: str
    tags: Optional[str] = ""
    summary: Optional[str] = ""
    content: str

class ProcedureUpdate(BaseModel):
    title: str
    equipment: str
    category: str
    tags: Optional[str] = ""
    summary: Optional[str] = ""
    content: str

class AskRequest(BaseModel):
    question: str

class SettingsUpdate(BaseModel):
    gemini_api_key: Optional[str] = ""

class LoginRequest(BaseModel):
    username: str
    password: str

# Dependências de Autenticação
def get_current_user(request: Request) -> Optional[dict]:
    token = request.cookies.get("docubrain_session")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    if not token:
        return None
    conn = database.get_connection()
    try:
        return auth.get_user_by_session(conn, token)
    finally:
        conn.close()

def require_user(user: Optional[dict] = Depends(get_current_user)) -> dict:
    if not user:
        raise HTTPException(status_code=401, detail="Sessão não autenticada ou expirada.")
    return user

def require_admin(user: dict = Depends(require_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Acesso restrito ao administrador. Seu usuário possui permissão apenas para consulta."
        )
    return user

# Rotas Web
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html"
    )

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    stats = database.get_stats()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"stats": stats, "user": user}
    )

# Rotas de Autenticação API
@app.post("/api/auth/login")
def login_endpoint(payload: LoginRequest, response: Response, request: Request):
    conn = database.get_connection()
    try:
        user = auth.authenticate_user(conn, payload.username, payload.password)
        if not user:
            raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")
        
        token = auth.create_session(conn, user["id"], days_valid=30)
        is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie(
            key="docubrain_session",
            value=token,
            max_age=30 * 86400,
            httponly=True,
            samesite="lax",
            secure=is_https
        )
        return {"status": "ok", "user": user}
    finally:
        conn.close()

@app.post("/api/auth/logout")
def logout_endpoint(response: Response, request: Request):
    token = request.cookies.get("docubrain_session")
    if token:
        conn = database.get_connection()
        try:
            auth.delete_session(conn, token)
        finally:
            conn.close()
    response.delete_cookie(key="docubrain_session")
    return {"status": "ok", "message": "Desconectado com sucesso"}

@app.get("/api/auth/me")
def me_endpoint(user: dict = Depends(require_user)):
    return user

# Rotas da API de Procedimentos
@app.get("/api/procedures")
def get_procedures(
    q: Optional[str] = Query(None, description="Termo de busca"),
    category: Optional[str] = Query(None, description="Filtro por categoria"),
    equipment: Optional[str] = Query(None, description="Filtro por equipamento"),
    user: dict = Depends(require_user)
):
    if q and q.strip():
        results = database.search_procedures(q)
    else:
        results = database.list_procedures(category, equipment)
    return results

@app.get("/api/procedures/{proc_id}")
def get_procedure_detail(proc_id: int, user: dict = Depends(require_user)):
    proc = database.get_procedure(proc_id)
    if not proc:
        raise HTTPException(status_code=404, detail="Procedimento não encontrado")
    
    # Converte o conteúdo markdown em HTML para visualização
    html_content = markdown.markdown(
        proc["content"],
        extensions=["fenced_code", "tables", "nl2br", "sane_lists"]
    )
    proc["html_content"] = html_content
    return proc

@app.post("/api/procedures")
def create_procedure(payload: ProcedureCreate, user: dict = Depends(require_admin)):
    new_id = database.save_procedure(
        title=payload.title,
        equipment=payload.equipment,
        category=payload.category,
        tags=payload.tags or "",
        summary=payload.summary or "",
        content=payload.content
    )
    return {"id": new_id, "message": "Procedimento cadastrado com sucesso!"}

@app.put("/api/procedures/{proc_id}")
def update_procedure(proc_id: int, payload: ProcedureUpdate, user: dict = Depends(require_admin)):
    exists = database.get_procedure(proc_id)
    if not exists:
        raise HTTPException(status_code=404, detail="Procedimento não encontrado")
    
    database.save_procedure(
        title=payload.title,
        equipment=payload.equipment,
        category=payload.category,
        tags=payload.tags or "",
        summary=payload.summary or "",
        content=payload.content,
        proc_id=proc_id
    )
    return {"id": proc_id, "message": "Procedimento atualizado com sucesso!"}

@app.delete("/api/procedures/{proc_id}")
def delete_procedure(proc_id: int, user: dict = Depends(require_admin)):
    success = database.delete_procedure(proc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Procedimento não encontrado")
    return {"message": "Procedimento excluído com sucesso!"}

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    ext = os.path.splitext(file.filename)[1].lower() if file.filename else ".png"
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Formato não suportado. Use PNG, JPG, JPEG, WEBP ou GIF.")
    
    filename = f"img_{uuid.uuid4().hex[:12]}{ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)

    contents = await file.read()
    if len(contents) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="A imagem deve ter no máximo 20MB.")

    with open(filepath, "wb") as f:
        f.write(contents)

    return {
        "url": f"/uploads/{filename}",
        "filename": filename
    }

ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".aac", ".flac"}

@app.post("/api/transcribe-audio")
async def transcribe_audio_endpoint(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    ext = os.path.splitext(file.filename)[1].lower() if file.filename else ".webm"
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        ext = ".webm"
    
    filename = f"audio_{uuid.uuid4().hex[:12]}{ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)

    contents = await file.read()
    if len(contents) > 35 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="O arquivo de áudio deve ter no máximo 35MB.")

    with open(filepath, "wb") as f:
        f.write(contents)

    try:
        structured_data = ai_service.transcribe_and_structure_audio(filepath)
        return structured_data
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao processar áudio com IA: {e}")
    finally:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass

ALLOWED_MANUAL_EXTENSIONS = {".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp", ".docx"}

@app.post("/api/upload-manual")
async def upload_manual_endpoint(
    file: UploadFile = File(...),
    focus: Optional[str] = Form(None),
    user: dict = Depends(require_admin)
):
    ext = os.path.splitext(file.filename)[1].lower() if file.filename else ".pdf"
    if ext not in ALLOWED_MANUAL_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Formato não suportado. Envie arquivos PDF, TXT, MD ou Imagens de manuais."
        )

    filename = f"manual_{uuid.uuid4().hex[:12]}{ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)

    contents = await file.read()
    if len(contents) > 45 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="O arquivo do manual deve ter no máximo 45MB.")

    with open(filepath, "wb") as f:
        f.write(contents)

    try:
        structured_data = ai_service.analyze_and_extract_manual(
            file_path=filepath,
            filename=file.filename or "manual.pdf",
            focus=focus
        )
        return structured_data
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao analisar manual com IA: {e}")
    finally:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass

@app.post("/api/ask")
def ask_question(payload: AskRequest, user: dict = Depends(require_user)):
    result = ai_service.ask_ai(payload.question)
    # Renderiza markdown da resposta da IA para HTML
    result["html_answer"] = markdown.markdown(
        result["answer"],
        extensions=["fenced_code", "tables", "nl2br", "sane_lists"]
    )
    return result

@app.get("/api/stats")
def get_stats(user: dict = Depends(require_user)):
    return database.get_stats()

@app.get("/api/settings")
def get_settings(user: dict = Depends(require_admin)):
    key = database.get_setting("gemini_api_key", "")
    return {
        "has_key": bool(key),
        "status": "Ativa e Conectada" if bool(key) else "Não configurada"
    }

@app.post("/api/settings")
def save_settings(payload: SettingsUpdate, user: dict = Depends(require_admin)):
    database.set_setting("gemini_api_key", payload.gemini_api_key.strip() if payload.gemini_api_key else "")
    return {"message": "Configurações salvas com sucesso!"}

def _restart_server():
    import time
    time.sleep(1)
    os._exit(0)

@app.post("/api/system/update")
def trigger_system_update(token: str = Query(...)):
    if token != UPDATE_TOKEN:
        raise HTTPException(status_code=403, detail="Token de atualização inválido")
    
    updated_via = ""
    output_log = ""
    
    # 1. Tenta via git pull se git estiver disponível
    try:
        git_res = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=20
        )
        if git_res.returncode == 0:
            updated_via = "git"
            output_log = git_res.stdout
    except Exception:
        pass

    # 2. Se git não rodou, baixa direto o zip do GitHub
    if not updated_via:
        try:
            zip_url = "https://github.com/Breno-Zocatelli/docubrain-procedimentos/archive/refs/heads/main.zip"
            req = urllib.request.Request(zip_url, headers={"User-Agent": "DocuBrain-Updater"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                zip_data = resp.read()
            
            with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
                for member in z.infolist():
                    parts = member.filename.split("/", 1)
                    if len(parts) > 1 and parts[1]:
                        rel_path = parts[1]
                        # Nunca sobrescreve os dados e anotações do usuário
                        if rel_path.startswith("data/"):
                            continue
                        target_file = os.path.join(PROJECT_ROOT, rel_path)
                        if member.is_dir():
                            os.makedirs(target_file, exist_ok=True)
                        else:
                            os.makedirs(os.path.dirname(target_file), exist_ok=True)
                            with z.open(member) as source, open(target_file, "wb") as dest:
                                shutil.copyfileobj(source, dest)
            
            updated_via = "zip_download"
            output_log = "Arquivos atualizados com sucesso diretamente do GitHub!"
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao atualizar: {e}")

    # Agenda reinício gracioso do contêiner Docker
    threading.Thread(target=_restart_server, daemon=True).start()

    return {
        "status": "success",
        "method": updated_via,
        "message": "Código atualizado com sucesso! Reiniciando contêiner...",
        "log": output_log
    }
