# ChatService Local Setup

## Core Requirements
- Python 3.10+
- MongoDB (local or Atlas)
- PostgreSQL 14+ with `pgvector` extension enabled
- RabbitMQ running on `localhost`
- OpenAI API key (required for booking assistant and corpus seeding)

## 1. Create Environment And Install Dependencies
```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Configure Environment Variables
Use `env_config/local.env` and set real values (do not commit secrets):

```sh
export ENV=local
export FLASK_ENV=development
export PYTHONPATH=/absolute/path/to/ChatService
export SECRET_KEY=<your-secret>

export DB_NAME=chat
export DB_PATH=mongodb://localhost:27017/

export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=appointments
export POSTGRES_USERNAME=<postgres-user>
export POSTGRES_PASSWORD=<postgres-password>

export OPENAI_API_KEY=<openai-key>

# Optional overrides
export CHAT_CONTEXT_LIMIT=30
export LLM_MODEL=gpt-3.5-turbo
export RAG_EMBEDDING_MODEL=text-embedding-3-small
export PGVECTOR_TABLE=knowledge_corpus_vectors
```

Load variables in your current shell:
```sh
source env_config/local.env
```

## 3. Configure PostgreSQL Schema
Create database:

```sql
CREATE DATABASE appointments;
```

Connect to `appointments` and create base booking tables used by the app:

```sql
CREATE TABLE IF NOT EXISTS service_providers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    service TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS service_slots (
    id BIGSERIAL PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES service_providers(id) ON DELETE CASCADE,
    available_date DATE NOT NULL,
    available_time TIME NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_service_providers_service ON service_providers(service);
CREATE INDEX IF NOT EXISTS idx_service_providers_name ON service_providers(name);
CREATE INDEX IF NOT EXISTS idx_service_slots_provider_date_time
    ON service_slots(provider_id, available_date, available_time);
```

Enable `pgvector` and create RAG corpus table/indexes:

```sh
psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USERNAME" -d "$POSTGRES_DB" \
  -f app/resources/bookslot/sql/pgvector_schema.sql
```

## 4. Configure MongoDB Schema
Use database `chat` and create required collections:

```javascript
use chat

db.createCollection("room")
db.createCollection("message")
db.createCollection("room_session")
```

Suggested indexes for core query paths:

```javascript
db.room.createIndex({ "room_mates.uuid": 1, room_type: 1 })
db.message.createIndex({ room_id: 1, created: -1 })
db.message.createIndex({ message_id: 1 }, { unique: true })
db.message.createIndex({ room_id: 1, sender_uuid: 1, created: 1 })
```

`room_session` TTL index is created automatically by the app at startup.

## 5. Seed Knowledge Corpus (Required For Agentic Booking)
Run after PostgreSQL schema setup and after setting `OPENAI_API_KEY`:

```sh
python -m app.resources.bookslot.seed_agentic_rag_corpus --clear-seed-rows
```

## 6. Run The Service
Start RabbitMQ first, then run the chat service:

```sh
python app/run.py
```

Service starts on `http://localhost:5001`.

## Critical Runtime Notes
- RabbitMQ is mandatory for message enqueue/consume flow (`chat_message` and `chat_delivery_updates` queues).
- Most HTTP APIs require JWT auth (`verify_jwt_in_request`); `/chat` is the simplest route to verify server startup.
- This service expects a separate user/auth service for end-to-end authenticated usage.

