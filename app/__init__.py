
from flask import Flask, g

from app.endpoints import endpoints
from app.models.extensions import socketio
from app.resources.chat.chat_blueprint import chat_api
from config import Config


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    socketio.init_app(app, cors_allowed_origins="*")

    @app.teardown_appcontext
    def close_mongo_client(exception=None):
        client = getattr(g, 'mongo_client', None)
        if client:
            client.close()

    app.register_blueprint(endpoints)
    app.register_blueprint(chat_api)
    return app