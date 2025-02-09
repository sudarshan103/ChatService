from bson import json_util

from flask import Blueprint, jsonify, render_template, request

from app.models.chat_repo import ChatRepo
from app.models.extensions import ApiJSONEncoder
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
