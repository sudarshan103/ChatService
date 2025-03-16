import json
import queue

from datetime import datetime
import redis
from flask_socketio import SocketIO
from pymongo import MongoClient
from flask import current_app, g

socketio = SocketIO()
message_queue = queue.Queue()
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)

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