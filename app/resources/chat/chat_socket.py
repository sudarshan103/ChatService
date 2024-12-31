import json

from app.constants import chat_message_queue
from flask_socketio import emit
from app.models.extensions import socketio
from app.resources.broker.message_sender import send_to_broker


@socketio.on('create_message')
def on_create_message(data):
    print("Received emitted message from client")
    try:
        # Input Validation
        if not data.get('room_id') or not data.get('room_id').strip():
            emit('error', {"error": "room_id cannot be empty."})
            return

        if not data.get('sender_name') or not data.get('sender_name').strip():
            emit('error', {"error": "sender_name cannot be empty."})
            return

        if not data.get('sender_uuid') or not data.get('sender_uuid').strip():
            emit('error', {"error": "sender_uuid cannot be empty."})
            return

        if not data.get('message') or not data.get('message').strip():
            emit('error', {"error": "Message cannot be empty."})
            return

        send_to_broker(json.dumps(data), chat_message_queue)

        emit('message_created', data)

    except Exception as e:
        emit('error', {"error": str(e)})