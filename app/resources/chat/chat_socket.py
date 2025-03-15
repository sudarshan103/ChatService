
import json
from datetime import datetime, timezone
from flask_socketio import emit
from app.constants import chat_message_queue, chat_delivery_update_queue
from app.models.extensions import socketio
from app.resources.broker.message_sender import enqueue_message
from app.utils.utils import is_integer


def on_create_message(data):
    print("Received emitted message from client")
    try:
        # Validate required fields
        message_id = data.get('message_id')
        if not message_id or not message_id.strip():
            emit('error', {"error": "message_id cannot be empty."})
            return

        room_id = data.get('room_id')
        if not room_id or not room_id.strip():
            emit('error', {"error": "room_id cannot be empty."})
            return

        sender_name = data.get('sender_name')
        if not sender_name or not sender_name.strip():
            emit('error', {"error": "sender_name cannot be empty."})
            return

        sender_uuid = data.get('sender_uuid')
        if not sender_uuid or not sender_uuid.strip():
            emit('error', {"error": "sender_uuid cannot be empty."})
            return

        message = data.get('message')
        if not message or not message.strip():
            emit('error', {"error": "Message cannot be empty."})
            return

        # Add metadata
        # data["action"] = 'message_received'
        # data["created"] = datetime.now(timezone.utc).isoformat()
        # emit(room_id, data, broadcast=True)

        socketio.start_background_task(
            target=enqueue_message,
            message=json.dumps(data),
            queue_name=chat_message_queue
        )

    except Exception as e:
        emit('error', {"error": str(e)})


def on_update_delivery_status(data):
    print("Received delivery acknowledgement from client")
    try:
        # Validate required fields
        room_id = data.get('room_id')
        if not room_id or not room_id.strip():
            emit('error', {"error": "room_id cannot be empty."})
            return

        reader_uuid = data.get('reader_uuid')
        if not reader_uuid or not reader_uuid.strip():
            emit('error', {"error": "Please provide message reader id."})
            return

        if not data.get('message_ids'):
            emit('error', {"error": "Please provide at least one message_id."})
            return

        if not is_integer(data.get('delivery_status')):
            emit('error', {"error": "Please provide delivery_status"})
            return

        # Add metadata
        data["action"] = 'delivery_updated'
        emit(room_id, data, broadcast=True)

        # Only enqueue for processing, don't emit here
        socketio.start_background_task(
            target=enqueue_message,
            message=data,
            queue_name=chat_delivery_update_queue
        )

    except Exception as e:
        emit('error', {"error": str(e)})