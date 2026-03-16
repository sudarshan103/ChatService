from flask_cors import CORS
from flask import Flask, g

from app.endpoints import endpoints
from app.resources.chat.chat_blueprint import chat_api
from config import Config
from app.models.extensions import mongodb
from app.repositories.chat_repository import MongoCollections

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app, resources={r"/*": {"origins": ["http://127.0.0.1:5000","http://localhost:5000"], "supports_credentials": True}})

    @app.teardown_appcontext
    def close_mongo_client(exception=None):
        client = getattr(g, 'mongo_client', None)
        if client:
            client.close()

    app.register_blueprint(endpoints)
    app.register_blueprint(chat_api)
    
    # Initialize MongoDB TTL index for room_session collection
    with app.app_context():
        _ensure_ttl_index()
    
    return app

def _ensure_ttl_index():
    """Create TTL index on room_session collection for automatic cleanup."""
    try:
        collection = mongodb()[MongoCollections.ROOM_SESSION]
        # Create TTL index: documents expire 10 minutes after last update
        collection.create_index(
            [('updated_at', 1)],
            expireAfterSeconds=Config.ROOM_SESSION_TTL,
            name='room_session_updated_at_ttl'
        )
    except Exception as e:
        pass