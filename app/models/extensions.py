import json
import os
import psycopg2

from psycopg2.extras import RealDictCursor

from datetime import datetime
from flask_socketio import SocketIO
from pymongo import MongoClient
from flask import current_app, g
from config import Config

socketio = SocketIO()


class PostgresConnection:
    """PostgreSQL connection wrapper with dict-style rows."""

    def __init__(self):
        self._connection = None
        self._connect()

    def _connect(self):
        self._connection = psycopg2.connect(
            host=Config.POSTGRES_HOST,
            port=Config.POSTGRES_PORT,
            user=Config.POSTGRES_USERNAME,
            password=Config.POSTGRES_PASSWORD,
            dbname=Config.POSTGRES_DB,
        )
        self._connection.autocommit = True

    def _ensure_connection(self):
        if self._connection is None or self._connection.closed:
            self._connect()

    def cursor(self, *args, **kwargs):
        self._ensure_connection()
        kwargs.setdefault("cursor_factory", RealDictCursor)
        return self._connection.cursor(*args, **kwargs)

    def commit(self):
        self._ensure_connection()
        return self._connection.commit()

    def rollback(self):
        self._ensure_connection()
        return self._connection.rollback()

    def close(self):
        if self._connection and not self._connection.closed:
            self._connection.close()


db = PostgresConnection()

def get_mongo_client():
    if 'mongo_client' not in g:
        g.mongo_client = MongoClient(current_app.config['DB_PATH'])
    return g.mongo_client

def mongodb():
    client = get_mongo_client()
    return client[current_app.config['DB_NAME']]

class ApiJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)