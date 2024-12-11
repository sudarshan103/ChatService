import json
from datetime import date

from flask import Flask


from app.endpoints import endpoints
from app.resources.service_user.chat_blueprint import chat_api
from config import Config


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.register_blueprint(endpoints)
    app.register_blueprint(chat_api)
    return app