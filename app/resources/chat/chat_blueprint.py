
from flask import Blueprint, request, jsonify

from app import socketio
from flask_socketio import emit
from app.models.chat_repo import ChatRepo
from app.resources.core.auth import verify_auth_token

# Initialize the Blueprint
chat_api = Blueprint('chat_api', __name__)

@chat_api.route('/messages', methods=['GET'])
@verify_auth_token
def read_messages(*args, **kwargs):
    if not kwargs.get('room_id'):
        return jsonify({'message': 'Missing required fields'}), 400

    return jsonify({"message": "Message sent successfully"}), 200

@chat_api.route('/rooms', methods=['GET'])
@verify_auth_token
def read_messages(*args, **kwargs):
    if not kwargs.get('uuid'):
        return jsonify({'message': 'Missing required fields'}), 400

    return jsonify({"message": "Message sent successfully"}), 200

@socketio.on('create_message')
def handle_create_message(data):
    try:
        room_mates = data.get('room_mates', [])
        sender_uuid = data.get('sender_uuid')
        sender_name = data.get('sender_name')
        message_text = data.get('message')
        room_id = data.get('room_id')

        # Input Validation
        if not (room_mates and room_id):
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

        # Send response back to the client
        emit('message_created', {
            "room_id": room_id,
            "message": message
        })

    except Exception as e:
        emit('error', {"error": str(e)})