"""HTTP API for the RAG chat. Run with:  uvicorn src.api:app --reload

REST for chat management, Server-Sent Events (SSE) for streaming answers: the answer only
flows server -> browser, so SSE over a plain POST is simpler and more robust than WebSockets.
"""
import json
import logging
from contextlib import asynccontextmanager

import os
import secrets
import threading
from dataclasses import dataclass

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from . import accounts, config, db, rerank, retriever, sessions, settings, training
from .loader import SUPPORTED_EXTENSIONS
from .rag import answer_stream
from .vectorstore import get_collection

log = logging.getLogger("rag.api")
FRONTEND_DIR = config.ROOT_DIR / "frontend" / "dist"  # built with `npm run build`
SNIPPET_CHARS = 220
MAX_PASSAGE_CHARS = 4000


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    _bootstrap_admin()
    settings.load()
    _auto_index()
    threading.Thread(target=_warm_up, daemon=True, name="warm-up").start()
    yield


def _auto_index() -> None:
    """With RAG_AUTO_INDEX=1 (set in the Docker setup), index data/ on start if nothing is indexed yet."""
    if os.environ.get("RAG_AUTO_INDEX", "").lower() not in ("1", "true", "yes"):
        return
    try:
        has_files = config.DATA_DIR.is_dir() and any(
            p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS for p in config.DATA_DIR.iterdir()
        )
        if has_files and get_collection().count() == 0:
            training.train_all()
            log.info("indexing the documents in %s (first start)", config.DATA_DIR)
    except Exception:
        log.exception("auto-index failed; use Rebuild index in the admin panel")


def _warm_up() -> None:
    """Load the reranker and build the search index before the first question, so it is not slow."""
    try:
        rerank.warm_up()
        retriever.get_corpus(get_collection())
    except Exception:
        log.exception("warm-up failed (the first question will be slower)")


def _bootstrap_admin() -> None:
    """Create the first admin from RAG_ADMIN_USER / RAG_ADMIN_PASSWORD when no account exists yet."""
    user, password = os.environ.get("RAG_ADMIN_USER"), os.environ.get("RAG_ADMIN_PASSWORD")
    if user and password and not accounts.has_users():
        accounts.create_user(user, password, is_admin=True)
        log.info("created admin account %r from the environment", user)


app = FastAPI(title="RAG Chat", lifespan=lifespan)

AUTH_COOKIE = "rag_auth"
ANON_COOKIE = "rag_anon"
throttle = accounts.LoginThrottle()


@dataclass
class Identity:
    """Who is asking. Signed-in users own chats as 'user:<id>', visitors as 'anon:<cookie>'."""
    owner: str
    user: dict | None


def _set_cookie(response: Response, name: str, value: str, days: int) -> None:
    response.set_cookie(name, value, max_age=days * 86400, httponly=True, samesite="lax", path="/")


def identity(request: Request, response: Response) -> Identity:
    user = accounts.user_for_token(request.cookies.get(AUTH_COOKIE))
    if user:
        return Identity(f"user:{user['id']}", user)
    anon = request.cookies.get(ANON_COOKIE)
    if not anon or len(anon) != 32 or not anon.isalnum():
        anon = secrets.token_hex(16)
        _set_cookie(response, ANON_COOKIE, anon, 365)
    return Identity(f"anon:{anon}", None)


def require_admin(who: Identity = Depends(identity)) -> Identity:
    if who.user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    if not who.user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return who


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class NewChat(BaseModel):
    title: str = Field(default=sessions.DEFAULT_TITLE, min_length=1, max_length=80)


class RenameChat(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class UserMessage(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    documents: list[str] | None = Field(default=None, max_length=20)  # limit the search to these files


def _require_chat(chat_id: str, owner: str) -> dict:
    chat = sessions.get_chat(chat_id, owner)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _public_sources(passages: list) -> list[dict]:
    """The passages behind an answer as the UI and the saved chat keep them (full text, so the viewer
    shows exactly what the model read even if the document is re-indexed later)."""
    return [
        {
            "n": p["n"], "id": p["id"], "source": p["source"], "section": p["section"], "role": p["role"],
            "page": p["page_start"] or None, "page_end": p["page_end"] or None,
            "score": None if p["score"] is None else round(p["score"], 3),
            "snippet": " ".join(p["body"].split())[:SNIPPET_CHARS], "text": p["body"][:MAX_PASSAGE_CHARS],
        }
        for p in passages
    ]


def _history_pairs(messages: list[dict]) -> list[dict]:
    """Recent (question, answer) pairs from the stored chat, oldest first."""
    pairs, pending = [], None
    for m in messages:
        if m["role"] == "user":
            pending = m["content"]
        elif pending is not None:
            pairs.append({"question": pending, "answer": m["content"]})
            pending = None
    return pairs[-config.CHAT_HISTORY_TURNS :]


@app.get("/api/health")
def health():
    return {"status": "ok", "model": config.LLM_MODEL, "embed_model": config.EMBED_MODEL}


@app.post("/api/auth/register", status_code=201)
def register(body: Credentials, response: Response, request: Request):
    try:
        user = accounts.create_user(body.username, body.password)
    except accounts.AccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    _set_cookie(response, AUTH_COOKIE, accounts.start_session(user["id"]), accounts.SESSION_DAYS)
    return user


@app.post("/api/auth/login")
def login(body: Credentials, response: Response, request: Request):
    key = request.client.host if request.client else "unknown"
    if throttle.blocked(key):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
    user = accounts.authenticate(body.username, body.password)
    if user is None:
        throttle.record_failure(key)
        raise HTTPException(status_code=401, detail="Wrong username or password")
    throttle.clear(key)
    _set_cookie(response, AUTH_COOKIE, accounts.start_session(user["id"]), accounts.SESSION_DAYS)
    return user


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response):
    accounts.end_session(request.cookies.get(AUTH_COOKIE))
    response.delete_cookie(AUTH_COOKIE, path="/")


@app.get("/api/auth/me")
def me(who: Identity = Depends(identity)):
    return {"user": who.user}


@app.get("/api/chats")
def list_chats(who: Identity = Depends(identity)):
    return sessions.list_chats(who.owner)


@app.post("/api/chats", status_code=201)
def create_chat(body: NewChat | None = None, who: Identity = Depends(identity)):
    return sessions.create_chat(who.owner, (body or NewChat()).title)


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str, who: Identity = Depends(identity)):
    return _require_chat(chat_id, who.owner)


@app.patch("/api/chats/{chat_id}")
def rename_chat(chat_id: str, body: RenameChat, who: Identity = Depends(identity)):
    if not sessions.rename_chat(chat_id, who.owner, body.title.strip()):
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"id": chat_id, "title": body.title.strip()}


@app.delete("/api/chats/{chat_id}", status_code=204)
def delete_chat(chat_id: str, who: Identity = Depends(identity)):
    if not sessions.delete_chat(chat_id, who.owner):
        raise HTTPException(status_code=404, detail="Chat not found")


# ---- admin: runtime settings ----

class SettingsUpdate(BaseModel):
    values: dict[str, bool | float | int | str]


class SettingsReset(BaseModel):
    keys: list[str] | None = None


@app.get("/api/admin/settings")
def admin_settings(_: Identity = Depends(require_admin)):
    return {"settings": settings.current()}


@app.put("/api/admin/settings")
def admin_update_settings(body: SettingsUpdate, _: Identity = Depends(require_admin)):
    try:
        settings.update(body.values)
    except settings.SettingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"settings": settings.current()}


@app.post("/api/admin/settings/reset")
def admin_reset_settings(body: SettingsReset | None = None, _: Identity = Depends(require_admin)):
    try:
        settings.reset((body or SettingsReset()).keys)
    except settings.SettingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"settings": settings.current()}


# ---- admin: documents and indexing ("training") ----

@app.get("/api/admin/documents")
def admin_documents(_: Identity = Depends(require_admin)):
    return {"documents": training.list_documents(), "jobs": training.recent_jobs()}


@app.put("/api/admin/documents/{filename}", status_code=202)
async def admin_upload(filename: str, request: Request, train: bool = True, _: Identity = Depends(require_admin)):
    """Raw file body (no multipart dependency). Indexing starts right away unless train=false.

    Answers with the outcome: "new", "replaced" (same name, new content) or "unchanged" (identical
    file already stored; it is only re-indexed if it never was). The same content under another name is a 409.
    """
    declared = int(request.headers.get("content-length") or 0)
    if declared > training.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is too large")
    body = await request.body()
    try:
        saved = await run_in_threadpool(training.save_upload, filename, body)
    except training.DuplicateDocument as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except training.DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    name, status = saved["name"], saved["status"]
    needs_index = train and not (status == "unchanged" and training.is_indexed(name))
    return {"name": name, "status": status, "job": training.train_document(name) if needs_index else None}


@app.delete("/api/admin/documents/{filename}", status_code=204)
def admin_delete(filename: str, _: Identity = Depends(require_admin)):
    try:
        existed = training.delete_document(filename)
    except training.DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not existed:
        raise HTTPException(status_code=404, detail="Document not found")


@app.post("/api/admin/documents/{filename}/train", status_code=202)
def admin_train(filename: str, _: Identity = Depends(require_admin)):
    try:
        name = training.safe_name(filename)
    except training.DocumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not (config.DATA_DIR / name).is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    return training.train_document(name)


@app.post("/api/admin/reindex", status_code=202)
def admin_reindex(_: Identity = Depends(require_admin)):
    return training.train_all()


@app.post("/api/chats/{chat_id}/messages")
def send_message(chat_id: str, body: UserMessage, who: Identity = Depends(identity)):
    """Store the question, then stream the answer as SSE events: meta, sources, token*, grounding, done."""
    chat = _require_chat(chat_id, who.owner)
    history = _history_pairs(chat["messages"])
    question = body.content.strip()
    if not question:
        raise HTTPException(status_code=422, detail="Message is empty")

    sessions.add_message(chat_id, "user", question)
    new_title = sessions.title_if_default(chat_id, question)

    _DONE = object()

    async def events():
        # Async generator: Starlette closes it when the client disconnects, so the
        # `finally` below always runs and keeps whatever was generated so far.
        answer, sources, checks = "", [], None
        gen = answer_stream(question, history=history, documents=body.documents)
        try:
            if new_title:
                yield _sse("meta", {"title": new_title})
            while True:
                item = await run_in_threadpool(next, gen, _DONE)  # model call blocks: keep it off the event loop
                if item is _DONE:
                    break
                kind, value = item
                if kind == "sources":
                    sources = _public_sources(value)
                    yield _sse("sources", {"sources": sources})
                elif kind == "grounding":
                    checks = value
                    yield _sse("grounding", value)
                else:
                    answer += value
                    yield _sse("token", {"text": value})
            yield _sse("done", {})
        except Exception:
            log.exception("answer generation failed")
            yield _sse("error", {"message": "The model could not answer right now. Is Ollama running?"})
        finally:
            try:
                gen.close()
            except ValueError:  # a model step is still in flight; it ends on its own
                pass
            if answer.strip():
                sessions.add_message(chat_id, "assistant", answer, sources, checks)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Mounted last so /api/* routes win. Serves the built React app at "/" (in dev, use `npm run dev`).
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
