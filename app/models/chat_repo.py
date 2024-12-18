import uuid
from datetime import datetime, timezone

from app.models.extensions import mongodb


class ChatRepo:

    @staticmethod
    def create_room(room_mates):
        room_mate_uuids = sorted([mate['uuid'] for mate in room_mates])

        existing_room = mongodb()['room'].find_one({
            "room_mates.uuid": {"$all": room_mate_uuids},
            "room_type": 0
        })

        if existing_room:
            return existing_room['room_id']

        # Create a new room
        room_id = str(uuid.uuid4())
        if len(room_mates) == 2:
            room_name = room_mates[1]['name']
        else:
            room_name = "Group conversation"

        new_room = {
            "room_id": room_id,
            "created": datetime.now(timezone.utc).isoformat(),
            "updated": datetime.now(timezone.utc).isoformat(),
            "room_type": 0,
            "room_name": room_name,
            "room_mates": room_mates,
            "active": True
        }
        mongodb()['room'].insert_one(new_room)
        return room_id

    @staticmethod
    def create_message(room_id, sender_uuid, sender_name, message_text):
        message_id = str(uuid.uuid4())
        message = {
            "message_id": message_id,
            "room_id": room_id,
            "created": datetime.now(timezone.utc).isoformat(),
            "updated": datetime.now(timezone.utc).isoformat(),
            "sender_uuid": sender_uuid,
            "sender_name": sender_name,
            "message": message_text,
            "delivery_status": 0,
            "delivery_status_trail": [],
            "active": True
        }
        mongodb()['message'].insert_one(message)
        return message