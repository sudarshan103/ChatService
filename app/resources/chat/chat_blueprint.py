
from flask import Blueprint, jsonify

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
def get_rooms(*args, **kwargs):
    if not kwargs.get('uuid'):
        return jsonify({'message': 'Missing required fields'}), 400

    return jsonify({"message": "Message sent successfully"}), 200