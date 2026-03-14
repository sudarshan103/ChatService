import json
import re
from datetime import datetime, timedelta, timezone, time as dt_time

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.models.extensions import db
from config import Config


def _normalize_specialty_text(value: str) -> str:
    normalized = re.sub(r"[^a-z\s]", " ", (value or "").lower())
    return " ".join(normalized.split())


def _resolve_specialty_with_llm(user_specialty: str, available_specialties: list[str]) -> str | None:
    """Map free-text specialty to one of the DB specialties using the configured LLM."""
    normalized_user_specialty = _normalize_specialty_text(user_specialty)
    if not normalized_user_specialty or not available_specialties:
        return None

    options = "\n".join(f"- {specialty}" for specialty in available_specialties)
    prompt = f"""
You are a medical specialty normalizer.
Map the user specialty text to exactly one option from the list.

Rules:
- Return ONLY one exact option from the list, or NONE.
- Do not explain.

User text: {user_specialty}
Options:
{options}
""".strip()

    try:
        llm = ChatOpenAI(model=Config.LLM_MODEL, temperature=0)
        content = (llm.invoke(prompt).content or "").strip()
    except Exception:
        return None

    if not content:
        return None

    candidate = content.splitlines()[0].strip().strip('"').strip("'")
    if candidate.upper() == "NONE":
        return None

    normalized_candidate = _normalize_specialty_text(candidate)
    for specialty in available_specialties:
        if normalized_candidate == _normalize_specialty_text(specialty):
            return specialty

    return None


def infer_tomorrow_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")


def search_medical_knowledge(query: str) -> str:
    """Retrieve specialty and doctor-profile context from pgvector.

    Steps:
    1. Convert query to embedding using OpenAI embeddings
    2. Run pgvector similarity search
    3. Return top retrieved context docs
    """
    embeddings = OpenAIEmbeddings(model=Config.RAG_EMBEDDING_MODEL)
    query_embedding = embeddings.embed_query(query)
    vector_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    cursor = db.cursor()

    sql = f"""
        SELECT record_type, content, specialty, provider_id, doctor_name, specialty_tags
        FROM {Config.PGVECTOR_TABLE}
        ORDER BY embedding <-> %s::vector
        LIMIT 5
    """

    cursor.execute(sql, (vector_literal,))

    rows = cursor.fetchall() or []
    cursor.close()

    matches = [
        {
            "record_type": row.get("record_type"),
            "content": row.get("content"),
            "specialty": row.get("specialty"),
            "provider_id": row.get("provider_id"),
            "doctor_name": row.get("doctor_name"),
            "specialty_tags": row.get("specialty_tags") or [],
        }
        for row in rows
    ]

    return json.dumps(
        {
            "query": query,
            "matches": matches,
            "count": len(matches),
        }
    )


def find_doctors_by_specialty(specialty: str, limit: int = 5) -> str:
    """Return doctors that belong to a specialty from service_providers."""
    cursor = db.cursor()
    direct_sql = """
        SELECT id, name, service
        FROM service_providers
        WHERE service ILIKE %s
        ORDER BY name ASC
        LIMIT %s
    """
    cursor.execute(direct_sql, (f"%{specialty}%", limit))
    direct_rows = cursor.fetchall() or []

    if len(direct_rows) >= limit:
        rows = direct_rows
    else:
        cursor.execute(
            """
            SELECT id, name, service
            FROM service_providers
            ORDER BY name ASC
            """
        )
        all_rows = cursor.fetchall() or []

        available_specialties = list(
            {
                row.get("service")
                for row in all_rows
                if row.get("service") and _normalize_specialty_text(row.get("service"))
            }
        )

        llm_specialty = _resolve_specialty_with_llm(specialty, sorted(available_specialties))

        rows = list(direct_rows)
        seen_provider_ids = {row.get("id") for row in rows}

        if llm_specialty:
            normalized_llm_specialty = _normalize_specialty_text(llm_specialty)
            for row in all_rows:
                provider_id = row.get("id")
                provider_specialty = _normalize_specialty_text(row.get("service") or "")
                if provider_id in seen_provider_ids or provider_specialty != normalized_llm_specialty:
                    continue
                seen_provider_ids.add(provider_id)
                rows.append(row)
                if len(rows) >= limit:
                    break

    cursor.close()

    doctors = [
        {"provider_id": row.get("id"), "name": row.get("name"), "specialty": row.get("service")}
        for row in rows
    ]

    return json.dumps(
        {
            "specialty": specialty,
            "doctors": doctors,
            "count": len(doctors),
        }
    )


def _normalize_doctor_name_query(value: str) -> str:
    normalized = re.sub(r"\s+", " ", (value or "").replace(".", " ")).strip()
    if normalized.lower().startswith("dr "):
        normalized = normalized[3:].strip()
    return normalized


def find_doctors_by_name(provider_name: str, limit: int = 5) -> str:
    """Return doctors by name from service_providers for direct name booking intents."""
    cursor = db.cursor()

    raw_query = (provider_name or "").strip()
    normalized_query = _normalize_doctor_name_query(raw_query)

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

    doctors = [
        {"provider_id": row.get("id"), "name": row.get("name"), "specialty": row.get("service")}
        for row in rows
    ]

    return json.dumps(
        {
            "provider_name_query": provider_name,
            "doctors": doctors,
            "count": len(doctors),
        }
    )


def _get_all_provider_dates(provider_id: int) -> list[str]:
    cursor = db.cursor()
    cursor.execute(
        """
        SELECT DISTINCT DATE(available_date) AS available_date
        FROM service_slots
        WHERE provider_id = %s
        ORDER BY DATE(available_date)
        """,
        (provider_id,),
    )
    rows = cursor.fetchall() or []
    cursor.close()

    dates: list[str] = []
    for row in rows:
        raw_date = row.get("available_date")
        if raw_date:
            dates.append(raw_date if isinstance(raw_date, str) else raw_date.strftime("%Y-%m-%d"))
    return dates


def _normalize_requested_date(value: str | None) -> str | None:
    """Normalize user date text to YYYY-MM-DD using the configured LLM."""
    raw = (value or "").strip()
    if not raw:
        return None

    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = f"""
You are a date normalizer for appointment booking.
Today's date is {today_iso} (UTC).

Extract the intended appointment date from the user's message and convert it to exactly one ISO date in YYYY-MM-DD format.
Rules:
- Output ONLY one value: either YYYY-MM-DD or NONE.
- Resolve relative terms using today's date.
- The input may contain extra words (for example confirmations like "yes" or "please"); ignore non-date words.
- Handle minor spelling mistakes in date words when intent is clear.
- If the input is ambiguous, invalid, or does not specify a date, output NONE.

User date text: {raw}
""".strip()

    try:
        llm = ChatOpenAI(model=Config.LLM_MODEL, temperature=0)
        content = (llm.invoke(prompt).content or "").strip()
    except Exception:
        return None

    if not content:
        return None

    candidate = content.splitlines()[0].strip().strip('"').strip("'")
    if candidate.upper() == "NONE":
        return None

    try:
        return datetime.strptime(candidate, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def get_available_slots_agentic(provider_id: int, date: str | None = None) -> str:
    """Fetch provider slots for agentic flow without depending on appointments_llm_driven."""
    cursor = db.cursor()

    requested_date = (date or "").strip() or None
    normalized_date = _normalize_requested_date(requested_date)

    if requested_date and not normalized_date:
        return json.dumps(
            {
                "provider_id": provider_id,
                "date_filter": None,
                "slots": [],
                "count": 0,
                "all_available_dates": None,
                "next_available_date": None,
                "error": "invalid_date",
                "message": "Could not understand the date. Please share your preferred appointment date in natural language.",
            }
        )

    if normalized_date:
        query = """
            SELECT ss.available_date, ss.available_time
            FROM service_slots ss
            WHERE ss.provider_id = %s AND DATE(ss.available_date) = %s
            ORDER BY ss.available_date, ss.available_time
            LIMIT 5
        """
        cursor.execute(query, (provider_id, normalized_date))
    else:
        query = """
            SELECT ss.available_date, ss.available_time
            FROM service_slots ss
            WHERE ss.provider_id = %s
            ORDER BY ss.available_date, ss.available_time
            LIMIT 5
        """
        cursor.execute(query, (provider_id,))

    rows = cursor.fetchall() or []
    cursor.close()

    slots = []
    for row in rows:
        raw_date = row.get("available_date")
        raw_time = row.get("available_time")

        date_str = raw_date if isinstance(raw_date, str) else raw_date.strftime("%Y-%m-%d")

        if isinstance(raw_time, str):
            time_str = f"{raw_time}:00" if len(raw_time) == 5 else raw_time
        elif isinstance(raw_time, dt_time):
            time_str = raw_time.strftime("%H:%M:%S")
        elif isinstance(raw_time, timedelta):
            total_seconds = int(raw_time.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            time_str = f"{hours:02d}:{minutes:02d}:00"
        else:
            time_str = str(raw_time)

        slots.append({"date": date_str, "time": time_str})

    all_available_dates = None
    next_available_date = None
    if normalized_date and not slots:
        all_available_dates = _get_all_provider_dates(provider_id)
        next_available_date = all_available_dates[0] if all_available_dates else None

    return json.dumps(
        {
            "provider_id": provider_id,
            "date_filter": normalized_date,
            "slots": slots,
            "count": len(slots),
            "all_available_dates": all_available_dates,
            "next_available_date": next_available_date,
        }
    )


def get_doctor_availability(provider_id: int, date: str | None = None) -> str:
    """LangChain tool wrapper that reuses canonical slot retrieval."""
    return get_available_slots_agentic(provider_id=provider_id, date=date)
