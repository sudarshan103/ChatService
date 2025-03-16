import eventlet
eventlet.monkey_patch()
from flask_jwt_extended import JWTManager

from app import create_app
from app.models.extensions import socketio, message_queue, redis_client
from app.resources.broker.message_receiver import init_broker_message_listener
from app.resources.chat.chat_socket import on_create_message, on_update_delivery_status, handle_connect, \
    handle_disconnect, REDIS_KEY

app = create_app()
jwt = JWTManager(app)
redis_client.flushdb()
socketio.init_app(app, cors_allowed_origins="*", async_mode='eventlet', engineio_logger=True)

def message_broadcaster():
    print("Message broadcaster started")
    while True:
        try:
            with app.app_context():
                result = message_queue.get()
                print(f"Processing message: {result}")

                connected_clients = redis_client.hkeys(REDIS_KEY)

                if not connected_clients:
                    print("⚠️ No connected clients!")

                for sid in connected_clients:
                    print(f"🔹 Sending message to {sid}")
                    try:
                        socketio.emit(result['room_id'],result, to=sid)
                    except Exception as e:
                        print(f"❌ Error sending to {sid}: {e}")

                message_queue.task_done()
                eventlet.sleep(0)
        except Exception as e:
            print(f"❌ Error processing message: {e}")



with app.app_context():
    init_broker_message_listener(socketio, app)
    socketio.on_event("create_message", on_create_message)
    socketio.on_event("update_delivery_status", on_update_delivery_status)
    socketio.on_event("connect", handle_connect)
    socketio.on_event("disconnect", handle_disconnect)
    socketio.start_background_task(message_broadcaster)

if __name__ == '__main__':
    socketio.run(app,
                 debug=True,
                 host="0.0.0.0",
                 port=5001,
                 allow_unsafe_werkzeug=True)
