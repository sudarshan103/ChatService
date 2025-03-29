import eventlet
eventlet.monkey_patch()
from flask_jwt_extended import JWTManager

from app import create_app
from app.models.extensions import socketio, redis_client
from app.resources.broker.message_receiver import init_broker_message_listener
from app.resources.chat.chat_socket import on_create_message, on_update_delivery_status, check_messages, handle_connect, \
    handle_disconnect

app = create_app()
jwt = JWTManager(app)
redis_client.flushdb()
socketio.init_app(app, cors_allowed_origins="*", async_mode='eventlet', engineio_logger=True, max_http_buffer_size=1e8)

with app.app_context():
    init_broker_message_listener(socketio, app)
    socketio.on_event("create_message", on_create_message)
    socketio.on_event("update_delivery_status", on_update_delivery_status)
    socketio.on_event("connect", handle_connect)
    socketio.on_event("disconnect", handle_disconnect)

if __name__ == '__main__':
    socketio.run(app,
                 debug=True,
                 host="0.0.0.0",
                 port=5001,
                 allow_unsafe_werkzeug=True)
