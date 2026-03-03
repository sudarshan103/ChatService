import os

class Config:
    ENV = os.environ.get('ENV')
    SECRET_KEY = os.environ.get('SECRET_KEY')
    DB_NAME = os.environ.get('DB_NAME')
    DB_PATH = os.environ.get('DB_PATH')
    CHAT_CONTEXT_LIMIT = int(os.environ.get('CHAT_CONTEXT_LIMIT', 30))