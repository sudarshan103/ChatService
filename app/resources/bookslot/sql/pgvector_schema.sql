
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_corpus_vectors (
    id BIGSERIAL PRIMARY KEY,
    -- 'service_summary': describes a service category (e.g. specialty, practice area).
    -- 'provider_profile': describes an individual provider.
    record_type TEXT NOT NULL CHECK (record_type IN ('service_summary', 'provider_profile')),
    service_category TEXT NOT NULL,
    provider_id INTEGER REFERENCES service_providers(id),
    provider_name TEXT,
    service_tags TEXT[] NOT NULL DEFAULT '{}'::text[],
    content TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (record_type = 'provider_profile' AND provider_name IS NOT NULL AND provider_id IS NOT NULL)
        OR (record_type = 'service_summary' AND provider_id IS NULL AND provider_name IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_knowledge_corpus_vectors_record_type
    ON knowledge_corpus_vectors (record_type);

CREATE INDEX IF NOT EXISTS idx_knowledge_corpus_vectors_service_category
    ON knowledge_corpus_vectors (service_category);

CREATE INDEX IF NOT EXISTS idx_knowledge_corpus_vectors_provider_id
    ON knowledge_corpus_vectors (provider_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_corpus_vectors_service_tags
    ON knowledge_corpus_vectors USING gin (service_tags);

-- IVFFLAT index for approximate nearest-neighbor search. Run ANALYZE after bulk load.
CREATE INDEX IF NOT EXISTS idx_knowledge_corpus_vectors_embedding
    ON knowledge_corpus_vectors USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
