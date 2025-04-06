import json
from datetime import datetime, timezone

from bson import json_util

from flask import Blueprint, jsonify, request

from app.constants import chat_message_queue, chat_delivery_update_queue
from app.models.chat_repo import ChatRepo
from app.models.extensions import ApiJSONEncoder
from app.resources.broker.message_sender import enqueue_message
from app.resources.core.auth import verify_auth_token

# Initialize the Blueprint
chat_api = Blueprint('chat_api', __name__)

@chat_api.route('/room/messages', methods=['GET'])
@verify_auth_token
def read_messages(**kwargs):
    if not request.args.get('room_id'):
        return jsonify({'message': 'Missing required fields'}), 400
    messages = ChatRepo.get_recent_messages(request.args.get('room_id'))
    return json_util.dumps(messages, cls=ApiJSONEncoder)

@chat_api.route('/room/unread-messages', methods=['GET'])
@verify_auth_token
def get_unread_messages(**kwargs):
    if not request.args.get('room_id'):
        return jsonify({'message': 'Missing required fields'}), 400
    room_id = request.args.get('room_id')
    reader_uuid = request.args.get('reader_uuid')
    last_read_message_id = request.args.get('last_read_message_id') or ""
    messages = ChatRepo.get_unread_messages_for_reader(room_id, reader_uuid, last_read_message_id)
    return json_util.dumps(messages, cls=ApiJSONEncoder)

@chat_api.route('/room/by-participants', methods=['GET'])
@verify_auth_token
def get_room(**kwargs):
    room_mates = []
    user_self = kwargs.get('user_data')
    room_mates.append(dict(name=user_self['name'], uuid=user_self['uuid']))
    room_mates.append(dict(name=request.args.get('name'), uuid=request.args.get('uuid')))
    return jsonify(ChatRepo.create_room(room_mates))

@chat_api.route('/room/active-by-user', methods=['GET'])
@verify_auth_token
def get_rooms(*args, **kwargs):
    if not kwargs.get('uuid'):
        return jsonify({'message': 'Missing required fields'}), 400

    return jsonify({"message": "Message sent successfully"}), 200

@chat_api.route('/message', methods=['POST'])
@verify_auth_token
def create_message(*args, **kwargs):
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    data["created"] = datetime.now(timezone.utc).isoformat()
    enqueue_message(json.dumps(data), chat_message_queue)
    return jsonify(data), 200

@chat_api.route('/message/status', methods=['POST'])
@verify_auth_token
def update_message_status(*args, **kwargs):
    data = request.get_json()

    if not data:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    enqueue_message(json.dumps(data), chat_delivery_update_queue)
    return jsonify({"message": "Status submitted"}), 200
