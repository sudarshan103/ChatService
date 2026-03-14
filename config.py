import os

class Config:
    ENV = os.environ.get('ENV')
    SECRET_KEY = os.environ.get('SECRET_KEY')
    DB_NAME = os.environ.get('DB_NAME')
    DB_PATH = os.environ.get('DB_PATH')
    POSTGRES_HOST = os.environ.get('POSTGRES_HOST', 'localhost')
    POSTGRES_PORT = int(os.environ.get('POSTGRES_PORT', 5432))
    POSTGRES_DB = os.environ.get('POSTGRES_DB', 'appointments')
    POSTGRES_USERNAME = os.environ.get('POSTGRES_USERNAME')
    POSTGRES_PASSWORD = os.environ.get('POSTGRES_PASSWORD')
    CHAT_CONTEXT_LIMIT = int(os.environ.get('CHAT_CONTEXT_LIMIT', 30))
    LLM_MODEL = os.environ.get('LLM_MODEL', 'gpt-3.5-turbo')
    ROOM_SESSION_TTL = int(os.environ.get('CHAT_CONTEXT_LIMIT', 600))
    ENABLE_AGENTIC_RAG = os.environ.get('ENABLE_AGENTIC_RAG', 'true').lower() == 'true'
    RAG_EMBEDDING_MODEL = os.environ.get('RAG_EMBEDDING_MODEL', 'text-embedding-3-small')
    PGVECTOR_TABLE = os.environ.get('PGVECTOR_TABLE', 'medical_corpus_vectors')