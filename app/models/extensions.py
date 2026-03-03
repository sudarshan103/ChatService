import json
import os
import mysql.connector

from datetime import datetime
from flask_socketio import SocketIO
from pymongo import MongoClient
from flask import current_app, g

socketio = SocketIO()

db = mysql.connector.connect(
    host="localhost",
    user=os.getenv('MYSQL_USERNAME'),
    password=os.getenv('MYSQL_PASSWORD'),
    database="appointments"
)

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