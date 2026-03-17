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
    RAG_EMBEDDING_MODEL = os.environ.get('RAG_EMBEDDING_MODEL', 'text-embedding-3-small')
    PGVECTOR_TABLE = os.environ.get('PGVECTOR_TABLE', 'knowledge_corpus_vectors')

    # --- Booking system display/persona configuration ---
    # Human-readable term for a single service provider shown in user-facing responses.
    # Example: 'doctor', 'lawyer', 'mechanic', 'trainer'
    PROVIDER_DISPLAY_TERM = os.environ.get('PROVIDER_DISPLAY_TERM', 'doctor')

    # Human-readable term for the type of service/expertise.
    # Example: 'specialty', 'practice area', 'service type'
    SERVICE_DISPLAY_TERM = os.environ.get('SERVICE_DISPLAY_TERM', 'specialty')

    # Short persona description used in the system prompt intro.
    # Example: 'medical booking assistant', 'legal appointment scheduler', 'auto-service booking assistant'
    BOOKING_ASSISTANT_PERSONA = os.environ.get('BOOKING_ASSISTANT_PERSONA', 'medical booking assistant')
