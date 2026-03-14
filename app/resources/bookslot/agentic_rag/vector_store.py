import logging
from typing import Any

from langchain_openai import OpenAIEmbeddings

from app.models.extensions import db
from config import Config

logger = logging.getLogger(__name__)


class PgVectorRetriever:
    """Simple pgvector retriever over a single medical corpus table."""

    def __init__(self) -> None:
        self._embeddings = OpenAIEmbeddings(model=Config.RAG_EMBEDDING_MODEL)
        self._table_name = Config.PGVECTOR_TABLE

    def _embed(self, text: str) -> list[float]:
        return self._embeddings.embed_query(text)

    def similarity_search(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        if not query:
            return []

        embedding = self._embed(query)
        cursor = db.cursor()

        # pgvector cosine distance operator: smaller is closer.
        sql = f"""
            SELECT
                id,
                record_type,
                specialty,
                provider_id,
                doctor_name,
                specialty_tags,
                content,
                1 - (embedding <=> %s::vector) AS similarity
            FROM {self._table_name}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """

        try:
            vector_literal = "[" + ",".join(str(v) for v in embedding) + "]"
            cursor.execute(sql, (vector_literal, vector_literal, top_k))
            rows = cursor.fetchall() or []
        except Exception as exc:
            logger.error("pgvector similarity_search failed: %s", exc)
            rows = []
        finally:
            cursor.close()

        results = []
        for row in rows:
            results.append(
                {
                    "id": row.get("id"),
                    "record_type": row.get("record_type"),
                    "content": row.get("content"),
                    "specialty": row.get("specialty"),
                    "provider_id": row.get("provider_id"),
                    "doctor_name": row.get("doctor_name"),
                    "specialty_tags": row.get("specialty_tags") or [],
                    "similarity": float(row.get("similarity") or 0),
                }
            )
        return results
