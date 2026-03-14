# Agentic RAG Extension (LangChain + pgvector)

## Python Module Structure

```text
app/resources/bookslot/agentic_rag/
  __init__.py
  vector_store.py         # PgVectorRetriever over PostgreSQL pgvector
  tools.py                # LangChain tool functions
  workflow.py             # create_openai_functions_agent setup
  service.py              # Drop-in handle_user_input_agentic(...)
  seed_rag_corpus.py      # Executable seed script for pgvector corpus
app/models/
  schemas.py              # Shared Pydantic schemas (single source)
app/resources/bookslot/sql/
  pgvector_schema.sql     # pgvector DDL for medical corpus
```

## Agent Workflow

1. Parse user intent and infer likely condition from symptom text.
2. Infer best-fit specialty from user wording plus retrieved context.
3. Call `search_medical_knowledge(query)` to ground reasoning from pgvector.
4. Call `find_doctors_by_specialty(specialty, limit)` against `service_providers`.
5. Resolve requested date (`tomorrow` -> `YYYY-MM-DD`).
6. Call `get_doctor_availability(provider_id, date)` against `service_slots`.
7. Return concise slot suggestions as numbered options.

The orchestration is implemented with `create_openai_functions_agent` in `workflow.py`.

## Tool Interfaces

### `search_medical_knowledge`

Input:
- `query: str`

Output JSON:
- `query: str`
- `matches: list[object]`
- `count: int`

### `find_doctors_by_specialty`

Input:
- `specialty: str`
- `limit: int = 5`

Output JSON:
- `specialty: str`
- `doctors: list[{provider_id:int,name:str,specialty:str}]`
- `count: int`

### `get_doctor_availability`

Input:
- `provider_id: int`
- `date: str` (`YYYY-MM-DD`)

Output JSON:
- `provider_id: int`
- `date: str`
- `slots: list[{date:str,time:str}]`
- `count: int`

## Data Model for pgvector Table

`medical_corpus_vectors` columns:
- `record_type` (`specialty_summary` | `doctor_profile`)
- `specialty`
- `provider_id` (required for `doctor_profile`, foreign key to `service_providers.id`)
- `doctor_name` (required for `doctor_profile`)
- `specialty_tags text[]`
- `content`
- `embedding vector(1536)`

This table can hold:
- specialty summary chunks (short descriptions)
- doctor profile chunks with specialty tags

## Dataset-Specific Guide

If your `service_providers` table already contains these rows:

- `1 | Dr. Priya | Cardiologist`
- `2 | Dr. Sheetal | Gastroenterology`
- `3 | Dr. Nikhil Jadhav | Orthopedic`

use the bootstrap guide here:

- `app/resources/bookslot/agentic_rag/DOCTOR_DATASET_GUIDE.md`

One-command seed script:

- `python -m app.resources.bookslot.agentic_rag.seed_rag_corpus --clear-seed-rows`

Expected behavior for user text like `I have knee pain and want an appointment tomorrow`:

1. Agent infers symptom cluster (`knee pain`) and maps to `Orthopedic`.
2. RAG tool returns orthopedic-specialty evidence from pgvector.
3. `find_doctors_by_specialty` returns `Dr. Nikhil Jadhav` (`provider_id=3`).
4. `get_doctor_availability` is called for `provider_id=3` and tomorrow's date.
5. User receives numbered slot suggestions.
