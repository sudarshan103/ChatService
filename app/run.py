from flask_jwt_extended import JWTManager

from app import create_app
from app.models.extensions import socketio
from app.resources.broker.message_receiver import init_broker_message_listener
from app.resources.chat.chat_socket import *

app = create_app()
jwt = JWTManager(app)
socketio.init_app(app, cors_allowed_origins="*")
init_broker_message_listener()

if __name__ == '__main__':
    app.run(debug=True, port=5001)
    socketio.run(app,
                 debug=True,
                 host="0.0.0.0",
                 port=5002,
                 allow_unsafe_werkzeug=True,
                 cors_allowed_origins="*",
                 async_mode="threading")
