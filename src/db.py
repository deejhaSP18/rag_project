"""SQLAlchemy engine, session factory and table models (SQLite for now; swap DATABASE_URL to move)."""
import os
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from . import config

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{config.STORAGE_DIR / 'chats.db'}")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(unique=True)  # case-insensitive, see accounts.py
    password_hash: Mapped[str]
    is_admin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[str] = mapped_column(default=now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[str]


class Chat(Base):
    __tablename__ = "chats"
    __table_args__ = (Index("idx_chats_owner", "owner", "updated_at"),)

    id: Mapped[str] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(default="", server_default="")
    title: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=now)
    updated_at: Mapped[str] = mapped_column(default=now)
    messages: Mapped[list["Message"]] = relationship(
        back_populates="chat", order_by="Message.id", cascade="all, delete-orphan", passive_deletes=True
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_messages_role"),
        Index("idx_messages_chat", "chat_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    role: Mapped[str]
    content: Mapped[str]
    sources: Mapped[list] = mapped_column(JSON, default=list)
    checks: Mapped[dict | None] = mapped_column(JSON, default=None)  # grounding report for an answer
    created_at: Mapped[str] = mapped_column(default=now)
    chat: Mapped[Chat] = relationship(back_populates="messages")


class AppSetting(Base):
    """An admin-chosen override of a value in config.py (see settings.py)."""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[float | int | str] = mapped_column(JSON)


engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    if DATABASE_URL.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.close()


SessionLocal = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope():
    """One unit of work: commit on success, roll back on error."""
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    config.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    # Databases created before accounts existed: add the owner column in place.
    if "owner" not in {c["name"] for c in inspect(engine).get_columns("chats")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE chats ADD COLUMN owner VARCHAR NOT NULL DEFAULT ''"))
        Base.metadata.create_all(engine)  # creates the owner index
    if "checks" not in {c["name"] for c in inspect(engine).get_columns("messages")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE messages ADD COLUMN checks JSON"))
