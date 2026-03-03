import os
import sys

import eventlet
eventlet.monkey_patch()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.resources.chat.chat_socket import on_update_delivery_status
from flask_jwt_extended import JWTManager

from app import create_app
from app.models.extensions import socketio
from app.resources.broker.message_receiver import init_broker_message_listener

app = create_app()
jwt = JWTManager(app)
socketio.init_app(app, cors_allowed_origins="*", async_mode='eventlet', engineio_logger=True, max_http_buffer_size=1e8)

with app.app_context():
    init_broker_message_listener(socketio, app)
    socketio.on_event("update_delivery_status", on_update_delivery_status)

if __name__ == '__main__':
    socketio.run(app,
                 debug=True,
                 host="0.0.0.0",
                 port=5001,
                 allow_unsafe_werkzeug=True)
