import os
import markdown
from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional, List

from . import database
from . import ai_service

app = FastAPI(title="Base de Procedimentos Operacionais - DocuBrain", version="1.0.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Inicializa o banco de dados na inicialização
@app.on_event("startup")
def startup_event():
    database.init_db()

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
