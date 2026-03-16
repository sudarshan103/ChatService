from app.models.extensions import db
from config import Config
from datetime import datetime, timezone


class ProviderRepository:
    """Postgres-backed repository for provider, slot, and knowledge-corpus reads."""

    @staticmethod
    def search_vector_matches(vector_literal: str, limit: int = 5) -> list[dict]:
        cursor = db.cursor()
        sql = f"""
            SELECT record_type, content, service_category, provider_id, provider_name, service_tags
            FROM {Config.PGVECTOR_TABLE}
            ORDER BY embedding <-> %s::vector
            LIMIT %s
        """
        cursor.execute(sql, (vector_literal, limit))
        rows = cursor.fetchall() or []
        cursor.close()
        return rows

    @staticmethod
    def similarity_search(vector_literal: str, top_k: int = 3) -> list[dict]:
        cursor = db.cursor()
        sql = f"""
            SELECT
                id,
                record_type,
                service_category,
                provider_id,
                provider_name,
                service_tags,
                content,
                1 - (embedding <=> %s::vector) AS similarity
            FROM {Config.PGVECTOR_TABLE}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        cursor.execute(sql, (vector_literal, vector_literal, top_k))
        rows = cursor.fetchall() or []
        cursor.close()
        return rows

    @staticmethod
    def find_providers_by_service_like(service: str, limit: int = 5) -> list[dict]:
        cursor = db.cursor()
        query = """
            SELECT id, name, service
            FROM service_providers
            WHERE service ILIKE %s
            ORDER BY name ASC
            LIMIT %s
        """
        cursor.execute(query, (f"%{service}%", limit))
        rows = cursor.fetchall() or []
        cursor.close()
        return rows

    @staticmethod
    def list_all_providers() -> list[dict]:
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT id, name, service
            FROM service_providers
            ORDER BY name ASC
            """
        )
        rows = cursor.fetchall() or []
        cursor.close()
        return rows

    @staticmethod
    def list_distinct_services(limit: int = 100) -> list[str]:
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT DISTINCT TRIM(service) AS service
            FROM service_providers
            WHERE service IS NOT NULL AND TRIM(service) <> ''
            ORDER BY service ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cursor.fetchall() or []
        cursor.close()
        return [row.get("service") for row in rows if row.get("service")]

    @staticmethod
    def find_providers_by_name(raw_query: str, normalized_query: str, limit: int = 5) -> list[dict]:
        cursor = db.cursor()
        query = """
            SELECT id, name, service
            FROM service_providers
            WHERE name ILIKE %s OR name ILIKE %s
            ORDER BY name ASC
            LIMIT %s
        """
        cursor.execute(query, (f"%{raw_query}%", f"%{normalized_query}%", limit))
        rows = cursor.fetchall() or []
        cursor.close()
        return rows

    @staticmethod
    def get_slots(provider_id: int, normalized_date: str | None = None, limit: int = 5) -> list[dict]:
        cursor = db.cursor()
        if normalized_date:
            query = """
                SELECT ss.available_date, ss.available_time
                FROM service_slots ss
                WHERE ss.provider_id = %s AND DATE(ss.available_date) = %s
                ORDER BY ss.available_date, ss.available_time
                LIMIT %s
            """
            cursor.execute(query, (provider_id, normalized_date, limit))
        else:
            query = """
                SELECT ss.available_date, ss.available_time
                FROM service_slots ss
                WHERE ss.provider_id = %s
                ORDER BY ss.available_date, ss.available_time
                LIMIT %s
            """
            cursor.execute(query, (provider_id, limit))

        rows = cursor.fetchall() or []
        cursor.close()
        return rows

    @staticmethod
    def get_all_provider_dates(provider_id: int) -> list[dict]:
        utc_today = datetime.now(timezone.utc).date()
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT DISTINCT DATE(available_date) AS available_date
            FROM service_slots
            WHERE provider_id = %s
              AND DATE(available_date) >= %s
            ORDER BY DATE(available_date)
            """,
            (provider_id, utc_today),
        )
        rows = cursor.fetchall() or []
        cursor.close()
        return rows
