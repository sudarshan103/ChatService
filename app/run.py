import eventlet
eventlet.monkey_patch()
import json
from app.constants import chat_message_queue, REDIS_KEY

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

def message_broadcaster():
    print("Message broadcaster started")
    while True:
        try:
            with app.app_context():
                try:
                    # Get the message from Redis queue (Non-blocking)
                    queue_data = redis_client.brpop(chat_message_queue, timeout=2)

                    if queue_data:
                        # Extract message
                        queue_name, message_json = queue_data
                        print(f"Retrieved message from queue: {queue_name}, message: {message_json}")

                        # Ensure proper decoding if message_json is bytes
                        if isinstance(message_json, bytes):
                            message_json = message_json.decode('utf-8')
                            result = json.loads(message_json)
                            # Emit message to clients
                            connected_clients = redis_client.hkeys(REDIS_KEY)
                            if not connected_clients:
                                print("⚠️ No connected clients!")

                            for sid in connected_clients:
                                print(f"🔹 Sending message to {sid}")
                                try:
                                    socketio.emit(result['room_id'], result, to=sid)
                                except Exception as e:
                                    print(f"❌ Error sending to {sid}: {e}")


                except Exception as e:
                    print(f"⚠️ Error processing message: {e}")
                    import traceback
                    traceback.print_exc()

                eventlet.sleep(0.1)
        except Exception as e:
            print(f"❌ Error processing message: {e}")



with app.app_context():
    init_broker_message_listener(socketio, app)
    socketio.on_event("create_message", on_create_message)
    socketio.on_event("update_delivery_status", on_update_delivery_status)
    socketio.on_event("connect", handle_connect)
    socketio.on_event("disconnect", handle_disconnect)
    # socketio.on_event("check_messages", check_messages)
    socketio.start_background_task(message_broadcaster)

if __name__ == '__main__':
    socketio.run(app,
                 debug=True,
                 host="0.0.0.0",
                 port=5001,
                 allow_unsafe_werkzeug=True)
