import argparse

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.status import Status
from rich.table import Table

from . import config
from .ingest import ingest
from .rag import ask

console = Console()


def show_sources(hits):
    table = Table(title="Sources", show_header=True, header_style="bold cyan")
    table.add_column("#", width=3)
    table.add_column("File")
    table.add_column("Relevance", justify="right")
    for i, h in enumerate(hits, start=1):
        relevance = max(0.0, 1 - h["distance"]) * 100
        table.add_row(str(i), h["source"], f"{relevance:.0f}%")
    console.print(table)


def ask_and_render(question: str, top_k: int):
    answer_text = ""
    panel = Panel("[dim]Thinking...[/dim]", title="Answer", border_style="green")

    with Live(panel, console=console, refresh_per_second=20) as live:
        def on_token(piece):
            nonlocal answer_text
            answer_text += piece
            live.update(Panel(Markdown(answer_text), title="Answer", border_style="green"))

        answer, hits = ask(question, top_k=top_k, stream=True, on_token=on_token)

    if hits:
        show_sources(hits)


def main():
    parser = argparse.ArgumentParser(description="Local RAG over Ollama")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("ingest", help="Index documents from the data/ folder")

    ask_parser = subparsers.add_parser("ask", help="Ask a one-off question")
    ask_parser.add_argument("question", type=str)
    ask_parser.add_argument("--top-k", type=int, default=config.TOP_K)

    subparsers.add_parser("chat", help="Start an interactive chat session")

    admin_parser = subparsers.add_parser("create-admin", help="Create an admin account for the web UI")
    admin_parser.add_argument("username")

    serve_parser = subparsers.add_parser("serve", help="Run the web API and chat UI")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()

    if args.command == "ingest":
        console.print(Panel("[bold]Ingesting documents[/bold]", border_style="blue"))
        with Status("[bold blue]Embedding chunks...", console=console):
            ingest()
    elif args.command == "ask":
        ask_and_render(args.question, args.top_k)
    elif args.command == "create-admin":
        import getpass
        import os

        from . import accounts, db

        db.init_db()
        password = os.environ.get("RAG_ADMIN_PASSWORD") or getpass.getpass("Password: ")
        try:
            accounts.create_user(args.username, password, is_admin=True)
        except accounts.AccountError as exc:
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(1)
        console.print(f"[green]Admin account '{args.username}' created.[/green]")
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("src.api:app", host=args.host, port=args.port)
    elif args.command == "chat":
        console.print(
            Panel(
                f"Local RAG chat — model: [bold]{config.LLM_MODEL}[/bold] | embeddings: [bold]{config.EMBED_MODEL}[/bold]\n"
                "Type 'exit' or 'quit' to stop.",
                title="RAG Chat",
                border_style="magenta",
            )
        )
        while True:
            question = Prompt.ask("[bold yellow]You[/bold yellow]").strip()
            if question.lower() in {"exit", "quit"}:
                break
            if not question:
                continue
            ask_and_render(question, config.TOP_K)


if __name__ == "__main__":
    main()
