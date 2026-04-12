import json
import uuid
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from jose import JWTError, jwt

from security import (
    settings, verify_password, verify_totp, create_access_token,
    SECRET_KEY, ALGORITHM
)
from agent import run_agent, run_agent_stream, ROOT_DIR
from proposals import proposal_store, ProposalStatus
from git_workflow import GitWorkflow, GitWorkflowError
from observability import init_observability, ObservabilityConfig, AgentMetrics, RequestTraceStore
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry import trace

app = FastAPI(title="MkDocs Agentic Chatbox API")

# --- Observability ---
obs_config = ObservabilityConfig()
init_observability(obs_config)
agent_metrics = AgentMetrics()
trace_store = RequestTraceStore(db_path=obs_config.sqlite_path)
FastAPIInstrumentor.instrument_app(app)

import os as _os
from context_engine import ContextEngine, TokenBudget, ContextCompactor
from memory import SQLiteMemory

memory_store = SQLiteMemory(
    db_path=_os.path.join(_os.path.dirname(__file__), "data", "memory.db"),
    max_items=1000,
)
compactor = ContextCompactor(protected_turns=4, trigger_pct=0.5)
context_engine = ContextEngine(
    memory=memory_store,
    compactor=compactor,
    budget=TokenBudget(context_limit=128000),
)

# Allow requests from configured origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        # Set request.id on span AFTER call_next, when FastAPIInstrumentor span exists
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute("request.id", request_id)
        response.headers["X-Request-ID"] = request_id
        return response

app.add_middleware(RequestIdMiddleware)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return username

class LoginRequest(BaseModel):
    username: str
    password: str
    totp: str

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    query: str
    history: List[ChatMessage] = []
    model: str = "openai"  # "openai", "deepseek", "qwen", "ollama"
    page_context: Optional[dict] = None  # {"title": "...", "url": "..."}


class ProposalFileResponse(BaseModel):
    path: str
    diff: str


class ProposalResponse(BaseModel):
    id: str
    status: str
    summary: str
    commit_message: str
    files: list[ProposalFileResponse]
    result: Optional[dict] = None

@app.get("/health")
def health_check():
    """Health check endpoint for service monitoring."""
    return {"status": "ok", "environment": settings.environment}


@app.post("/login")
def login(request: LoginRequest):
    if not verify_password(request.password, settings.app_admin_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    if request.username != settings.app_admin_username:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    if not verify_totp(settings.app_mfa_secret, request.totp):
        raise HTTPException(status_code=400, detail="Invalid MFA token")
    
    access_token = create_access_token(data={"sub": request.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/chat")
def chat_endpoint(request: ChatRequest, current_user: str = Depends(get_current_user)):
    try:
        history_dict = [{"role": msg.role, "content": msg.content} for msg in request.history]
        reply = run_agent(
            query=request.query,
            chat_history=history_dict,
            model_id=request.model,
            page_context=request.page_context,
            agent_metrics=agent_metrics,
            trace_store=trace_store,
            context_engine=context_engine,
        )
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest, current_user: str = Depends(get_current_user)):
    """Streaming chat endpoint. Returns newline-delimited JSON events:
    - {"type":"token","content":"..."}      — LLM token chunk
    - {"type":"tool_call","name":"..."}     — agent invoking a tool
    - {"type":"citations","sources":[...]}  — files used to answer
    - {"type":"done"}                       — stream complete
    - {"type":"error","detail":"..."}       — on failure
    """
    history_dict = [{"role": msg.role, "content": msg.content} for msg in request.history]

    async def event_generator():
        try:
            async for event in run_agent_stream(
                query=request.query,
                chat_history=history_dict,
                model_id=request.model,
                page_context=request.page_context,
                agent_metrics=agent_metrics,
                trace_store=trace_store,
                context_engine=context_engine,
            ):
                yield json.dumps(event) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "detail": str(e)}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(event_generator(), media_type="text/plain")


# --- PROPOSAL ENDPOINTS ---


@app.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, current_user: str = Depends(get_current_user)):
    """Retrieve a proposal by ID."""
    proposal = proposal_store.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return ProposalResponse(
        id=proposal.id,
        status=proposal.status.value,
        summary=proposal.summary,
        commit_message=proposal.commit_message,
        files=[ProposalFileResponse(path=f.path, diff=f.diff) for f in proposal.files],
        result=proposal.result,
    )


@app.post("/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str, current_user: str = Depends(get_current_user)):
    """Approve a proposal and execute the git workflow."""
    proposal = proposal_store.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Proposal is '{proposal.status.value}', not 'pending'",
        )

    proposal_store.update_status(proposal_id, ProposalStatus.EXECUTING)

    try:
        workflow = GitWorkflow(
            workspace_dir=ROOT_DIR,
            publish_dir=settings.publish_repo_dir,
            github_token=settings.github_token,
            publish_repo=settings.publish_repo,
        )
        result = workflow.execute(proposal)
        proposal_store.update_status(proposal_id, ProposalStatus.COMPLETED, result=result)
        return {"status": "completed", "result": result}
    except (GitWorkflowError, Exception) as e:
        proposal_store.update_status(
            proposal_id, ProposalStatus.FAILED, result={"error": str(e)},
        )
        raise HTTPException(status_code=500, detail=f"Git workflow failed: {e}")


@app.post("/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, current_user: str = Depends(get_current_user)):
    """Reject a proposal. No changes are made."""
    proposal = proposal_store.get(proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Proposal is '{proposal.status.value}', not 'pending'",
        )

    proposal_store.update_status(proposal_id, ProposalStatus.REJECTED)
    return {"status": "rejected"}
