import os
import markdown
import uuid
from fastapi import FastAPI, HTTPException, Request, Query, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
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

# Rotas Web
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    stats = database.get_stats()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"stats": stats}
    )

# Rotas da API
@app.get("/api/procedures")
def get_procedures(
    q: Optional[str] = Query(None, description="Termo de busca"),
    category: Optional[str] = Query(None, description="Filtro por categoria"),
    equipment: Optional[str] = Query(None, description="Filtro por equipamento")
):
    if q and q.strip():
        results = database.search_procedures(q)
    else:
        results = database.list_procedures(category, equipment)
    return results

@app.get("/api/procedures/{proc_id}")
def get_procedure_detail(proc_id: int):
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
def create_procedure(payload: ProcedureCreate):
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
def update_procedure(proc_id: int, payload: ProcedureUpdate):
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
def delete_procedure(proc_id: int):
    success = database.delete_procedure(proc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Procedimento não encontrado")
    return {"message": "Procedimento excluído com sucesso!"}

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}

@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
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
async def transcribe_audio_endpoint(file: UploadFile = File(...)):
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

@app.post("/api/ask")
def ask_question(payload: AskRequest):
    result = ai_service.ask_ai(payload.question)
    # Renderiza markdown da resposta da IA para HTML
    result["html_answer"] = markdown.markdown(
        result["answer"],
        extensions=["fenced_code", "tables", "nl2br", "sane_lists"]
    )
    return result

@app.get("/api/stats")
def get_stats():
    return database.get_stats()

@app.get("/api/settings")
def get_settings():
    key = database.get_setting("gemini_api_key", "")
    masked_key = f"{key[:6]}...{key[-4:]}" if len(key) > 10 else ("Configurada" if key else "")
    return {
        "has_key": bool(key),
        "masked_key": masked_key
    }

@app.post("/api/settings")
def save_settings(payload: SettingsUpdate):
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
