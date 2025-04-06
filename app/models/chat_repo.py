import uuid
from datetime import datetime, timezone

from app.models.extensions import mongodb


class ChatRepo:

    @staticmethod
    def receive_create_message_command(data):
        sender_uuid = data.get('sender_uuid')
        sender_name = data.get('sender_name')
        message_text = data.get('message')
        room_id = data.get('room_id')
        message_id = data.get('message_id')

        # Create the message
        message = ChatRepo.create_message(room_id, sender_uuid, sender_name, message_id, message_text)
        del message["_id"]
        return message

    @staticmethod
    def create_room(room_mates):
        room_details = {
            "room_type": 0
        }

        room_mate_uuids = sorted([mate['uuid'] for mate in room_mates])

        existing_room = mongodb()['room'].find_one({
            "room_mates.uuid": {"$all": room_mate_uuids},
            "room_type": 0
        })

        if existing_room:
            room_details["room_id"] = existing_room['room_id']
            room_details["room_name"] = existing_room['room_name']
            return room_details

        # Create a new room
        room_id = str(uuid.uuid4())
        room_details["room_id"] = room_id
        if len(room_mates) == 2:
            room_name = f"{room_mates[0]['name']},{room_mates[1]['name']}"
        else:
            room_name = "Group conversation"

        room_details["room_name"] = room_name

        new_room = {
            "created": datetime.now(timezone.utc).isoformat(),
            "updated": datetime.now(timezone.utc).isoformat(),
            "room_mates": room_mates,
            "active": True
        }
        new_room.update(room_details)

        mongodb()['room'].insert_one(new_room)
        return room_details

    @staticmethod
    def create_message(room_id, sender_uuid, sender_name, message_id, message_text):
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

    @staticmethod
    def get_recent_messages(room_id):
        query = {
            "active": True,
            "room_id": room_id
        }
        messages = list(
            mongodb()['message'].find(query)
            .sort("created", -1)  # Sort by created date in descending order (newest first)
            .limit(20)  # Limit to 20 most recent documents
        )[::-1]  # Reverse the list to get ascending order
        return messages

    @staticmethod
    def get_unread_messages_for_reader(room_id, reader_uuid, last_read_message_id=""):
        query = {
            "active": True,
            "room_id": room_id,
            "sender_uuid": {"$ne": reader_uuid},
            "delivery_status_trail": {
                "$not": {
                    "$elemMatch": {
                        "reader_uuid": reader_uuid
                    }
                }
            }
        }

        # If last_read_message_id is provided, fetch its created timestamp
        if last_read_message_id:
            last_read_message = mongodb()['message'].find_one({
                "message_id": last_read_message_id
            })
            if last_read_message:
                created_after = last_read_message.get("created")
                if created_after:
                    query["created"] = {"$gt": created_after}

        # Fetch matching messages
        messages = list(
            mongodb()['message'].find(query)
            .sort("created", 1)  # ascending order by time
        )
        return messages

    @staticmethod
    def update_delivery_status(data):
        reader_uuid = data.get('reader_uuid')
        message_ids = data.get('message_ids')
        delivery_status = data.get('delivery_status')
        trail_entry = {
            "reader_uuid": reader_uuid,
            "created": datetime.now(timezone.utc).isoformat(),
            "delivery_status":delivery_status
        }
        for message_id in message_ids:
            mongodb()['message'].update_one(
                {
                    "message_id": message_id,
                    "delivery_status_trail": {
                        "$not": {
                            "$elemMatch": {
                                "reader_uuid":  data.get('reader_uuid'),
                                "delivery_status": data.get('delivery_status')
                            }
                        }
                    }
                },
                {
                    "$push": {"delivery_status_trail": trail_entry},
                    "$set": {"delivery_status": data.get('delivery_status')}
                }
            )
