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
        if not data.get('room_mates', []):
            emit('error', {"error": "At least one user is required to chat with"})
            return
        if not data.get('message') or not data.get('message').strip():
            emit('error', {"error": "Message cannot be empty."})
            return

        send_to_broker(json.dumps(data), chat_message_queue)

        emit('message_created', {})

    except Exception as e:
        emit('error', {"error": str(e)})