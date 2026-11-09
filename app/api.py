"""HTTP API and browser demo. The mode property clearly distinguishes real LLM from baseline."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from .agent import investigate, AgentResult
from .baseline import investigate_offline
from .store import database_path, connect

app = FastAPI(
    title="FulfillGuard — Supply Chain AI Analytics Agent",
    version="1.0.0",
    description="LLM-assisted delivery performance analytics with SQL tools, evidence verification, and an auditable offline baseline.",
)

class AskRequest(BaseModel):
    question: str=Field(min_length=5,max_length=1500)
    mode: Literal['llm','baseline']='llm'

@app.get('/health')
def health():
    path=database_path()
    if not path.exists():
        return {'status':'missing_database','dataset_ready':False,'model_configured':bool(os.environ.get('GROQ_API_KEY'))}
    try:
        with connect() as con:
            count=con.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    except Exception:
        return {'status':'invalid_database','dataset_ready':False,'model_configured':bool(os.environ.get('GROQ_API_KEY'))}
    return {'status':'ok','dataset_ready':True,'orders':count,
            'data_kind':'synthetic_fixture' if count<100 else 'external_dataset_verify_provenance',
            'model_configured':bool(os.environ.get('GROQ_API_KEY'))}

@app.post('/investigate',response_model=AgentResult)
def ask(req:AskRequest):
    try:
        return investigate_offline(req.question) if req.mode=='baseline' else investigate(req.question)
    except (RuntimeError,FileNotFoundError) as exc:
        raise HTTPException(status_code=503,detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400,detail=str(exc)) from exc

@app.get('/',response_class=HTMLResponse)
def index():
    return Path(__file__).with_name('dashboard.html').read_text(encoding='utf-8')
