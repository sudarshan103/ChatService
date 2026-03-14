"""Agentic RAG booking package.

This package adds an opt-in LangChain agent workflow backed by PostgreSQL + pgvector.
It is intentionally isolated from the existing appointment flow to avoid regressions.
"""

from .workflow import create_agentic_booking_agent
from .service import handle_user_input_agentic

__all__ = ["create_agentic_booking_agent", "handle_user_input_agentic"]
