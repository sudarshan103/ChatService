
from app.models.chat_repo import ChatRepo
from flask_socketio import emit
from app.models.extensions import socketio


@socketio.on('create_message')
def on_create_message(data):
    print("Received emitted message from client")
    try:
        room_mates = data.get('room_mates', [])
        sender_uuid = data.get('sender_uuid')
        sender_name = data.get('sender_name')
        message_text = data.get('message')
        room_id = data.get('room_id')

        # Input Validation
        if not room_mates:
            emit('error', {"error": "At least one user is required to chat with"})
            return
        if not message_text or not message_text.strip():
            emit('error', {"error": "Message cannot be empty."})
            return

        # If no room_id is provided, create or retrieve room
        if not room_id:
            room_id = ChatRepo.create_room(room_mates)

        # Create the message
        message = ChatRepo.create_message(room_id, sender_uuid, sender_name, message_text)
        del message["_id"]

        # Send response back to the client
        emit('message_created', {
            "room_id": room_id,
            "message": message
        })

    except Exception as e:
        emit('error', {"error": str(e)})