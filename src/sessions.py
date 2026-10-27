"""Chat persistence through the ORM: one Chat per conversation, one Message per turn."""
import uuid

from sqlalchemy import select

from .db import Chat, Message, init_db, now, session_scope

DEFAULT_TITLE = "New chat"

__all__ = ["DEFAULT_TITLE", "init_db", "create_chat", "list_chats", "get_chat", "rename_chat", "delete_chat",
           "add_message", "title_if_default"]


def _summary(chat: Chat) -> dict:
    return {"id": chat.id, "title": chat.title, "created_at": chat.created_at, "updated_at": chat.updated_at}


def _owned(db, chat_id: str, owner: str) -> Chat | None:
    return db.scalars(select(Chat).where(Chat.id == chat_id, Chat.owner == owner)).first()


def create_chat(owner: str, title: str = DEFAULT_TITLE) -> dict:
    with session_scope() as db:
        chat = Chat(id=uuid.uuid4().hex, owner=owner, title=title)
        db.add(chat)
        db.flush()
        return _summary(chat)


def list_chats(owner: str) -> list[dict]:
    with session_scope() as db:
        chats = db.scalars(select(Chat).where(Chat.owner == owner).order_by(Chat.updated_at.desc()))
        return [_summary(c) for c in chats]


def get_chat(chat_id: str, owner: str) -> dict | None:
    """The chat, only if `owner` owns it (others get None, same as a missing chat)."""
    with session_scope() as db:
        chat = _owned(db, chat_id, owner)
        if chat is None:
            return None
        messages = [
            {"id": m.id, "role": m.role, "content": m.content, "sources": m.sources, "checks": m.checks, "created_at": m.created_at}
            for m in chat.messages
        ]
        return {**_summary(chat), "messages": messages}


def rename_chat(chat_id: str, owner: str, title: str) -> bool:
    with session_scope() as db:
        chat = _owned(db, chat_id, owner)
        if chat is None:
            return False
        chat.title = title
        return True


def delete_chat(chat_id: str, owner: str) -> bool:
    with session_scope() as db:
        chat = _owned(db, chat_id, owner)
        if chat is None:
            return False
        db.delete(chat)
        return True


def add_message(chat_id: str, role: str, content: str, sources: list | None = None, checks: dict | None = None) -> None:
    with session_scope() as db:
        db.add(Message(chat_id=chat_id, role=role, content=content, sources=sources or [], checks=checks))
        chat = db.get(Chat, chat_id)
        if chat is not None:
            chat.updated_at = now()


def title_if_default(chat_id: str, first_message: str) -> str | None:
    """Name a fresh chat after its first question. Returns the new title, if one was set."""
    title = " ".join(first_message.split())
    title = title if len(title) <= 48 else title[:47].rstrip() + "…"
    with session_scope() as db:
        chat = db.get(Chat, chat_id)
        if chat is None or chat.title != DEFAULT_TITLE:
            return None
        chat.title = title
        return title
