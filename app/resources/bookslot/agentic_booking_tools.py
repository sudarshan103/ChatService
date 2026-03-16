import json
from datetime import datetime, timedelta, timezone, time as dt_time
import re

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.repositories.provider_repository import ProviderRepository
from app.resources.core.openai_utils import llm_extract_single_line
from config import Config


def infer_tomorrow_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")


def search_knowledge_base(query: str) -> str:
    """Retrieve service-category and provider-profile context from pgvector.

    Steps:
    1. Convert query to embedding using OpenAI embeddings
    2. Run pgvector similarity search
    3. Return top retrieved context docs
    """
    embeddings = OpenAIEmbeddings(model=Config.RAG_EMBEDDING_MODEL)
    query_embedding = embeddings.embed_query(query)
    vector_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    rows = ProviderRepository.search_vector_matches(vector_literal=vector_literal, limit=5)

    matches = [
        {
            "record_type": row.get("record_type"),
            "content": row.get("content"),
            "service_category": row.get("service_category"),
            "provider_id": row.get("provider_id"),
            "provider_name": row.get("provider_name"),
            "service_tags": row.get("service_tags") or [],
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


def search_providers_by_service(service: str, limit: int = 5) -> str:
    """Return providers that match a service type from service_providers."""
    rows = ProviderRepository.find_providers_by_service_like(service=service, limit=limit)

    providers = [
        {"provider_id": row.get("id"), "name": row.get("name"), "service": row.get("service")}
        for row in rows
    ]

    return json.dumps(
        {
            "service": service,
            "providers": providers,
            "count": len(providers),
        }
    )


def _normalize_provider_name_query(value: str) -> str:
    """Extract the bare provider name from user input using the configured LLM.

    Removes titles and honorifics (Dr, Doctor, Prof, Mr, Ms, …) so the result
    can be used for a plain-name database lookup.  Falls back to the
    whitespace-normalised raw value if the LLM is unavailable or returns nothing.
    """
    raw = re.sub(r"\s+", " ", (value or "").replace(".", " ")).strip()
    if not raw:
        return ""

    provider_term = Config.PROVIDER_DISPLAY_TERM
    prompt = f"""
You are a name extractor for {provider_term} search.
Extract only the {provider_term}'s personal name from the input, stripping any titles or honorifics (Dr, Doctor, Prof, Mr, Ms, Sir, etc.).

Rules:
- Return ONLY the extracted name, or NONE if no name is present.
- Do not include any title or honorific in the output.
- Do not explain.

Input: {raw}
""".strip()

    return llm_extract_single_line(prompt) or raw


def search_providers_by_name(provider_name: str, limit: int = 5) -> str:
    """Return providers by name from service_providers for direct name booking intents."""
    raw_query = provider_name or ""
    normalized_query = _normalize_provider_name_query(raw_query)

    rows = ProviderRepository.find_providers_by_name(
        raw_query=raw_query,
        normalized_query=normalized_query,
        limit=limit,
    )

    providers = [
        {"provider_id": row.get("id"), "name": row.get("name"), "service": row.get("service")}
        for row in rows
    ]

    return json.dumps(
        {
            "provider_name_query": provider_name,
            "providers": providers,
            "count": len(providers),
        }
    )


def _get_all_provider_dates(provider_id: int) -> list[str]:
    rows = ProviderRepository.get_all_provider_dates(provider_id)

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

    candidate = llm_extract_single_line(prompt)
    if not candidate:
        return None

    try:
        return datetime.strptime(candidate, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def get_available_slots_agentic(provider_id: int, date: str | None = None) -> str:
    """Fetch provider slots for agentic booking flow."""
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

    rows = ProviderRepository.get_slots(provider_id=provider_id, normalized_date=normalized_date, limit=5)

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

    if not slots and normalized_date:
        all_dates = _get_all_provider_dates(provider_id)
        future_dates = [d for d in all_dates if d > normalized_date]
        next_date = future_dates[0] if future_dates else None
        return json.dumps(
            {
                "provider_id": provider_id,
                "date_filter": normalized_date,
                "slots": [],
                "count": 0,
                "all_available_dates": all_dates,
                "next_available_date": next_date,
            }
        )

    return json.dumps(
        {
            "provider_id": provider_id,
            "date_filter": normalized_date,
            "slots": slots,
            "count": len(slots),
            "all_available_dates": None,
            "next_available_date": None,
        }
    )
