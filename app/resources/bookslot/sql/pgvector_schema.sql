-- pgvector setup for RAG corpus in database: appointments
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS medical_corpus_vectors (
    id BIGSERIAL PRIMARY KEY,
    record_type TEXT NOT NULL CHECK (record_type IN ('specialty_summary', 'doctor_profile')),
    specialty TEXT NOT NULL,
    provider_id INTEGER REFERENCES service_providers(id),
    doctor_name TEXT,
    specialty_tags TEXT[] NOT NULL DEFAULT '{}'::text[],
    content TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (record_type = 'doctor_profile' AND doctor_name IS NOT NULL AND provider_id IS NOT NULL)
        OR (record_type = 'specialty_summary' AND provider_id IS NULL AND doctor_name IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_medical_corpus_vectors_record_type
    ON medical_corpus_vectors (record_type);

CREATE INDEX IF NOT EXISTS idx_medical_corpus_vectors_specialty
    ON medical_corpus_vectors (specialty);

CREATE INDEX IF NOT EXISTS idx_medical_corpus_vectors_provider_id
    ON medical_corpus_vectors (provider_id);

CREATE INDEX IF NOT EXISTS idx_medical_corpus_vectors_specialty_tags
    ON medical_corpus_vectors USING gin (specialty_tags);

-- IVFFLAT index for approximate nearest-neighbor search. Run ANALYZE after bulk load.
CREATE INDEX IF NOT EXISTS idx_medical_corpus_vectors_embedding
    ON medical_corpus_vectors USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
