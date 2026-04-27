"""Helper único para cargar prompts desde archivos Markdown.

Reutilizado por agent.py y por cada sub-agente para no duplicar lógica de I/O.
"""
from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt(name: str) -> str:
    """Carga un prompt por nombre (sin extensión). Ej: load_prompt('faq')."""
    if not name.endswith(".md"):
        name = f"{name}.md"
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")
