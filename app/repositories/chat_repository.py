import uuid
from datetime import datetime, timezone

from app.models.extensions import mongodb
from app.resources.bookslot.agentic_booking_workflow import run_agentic_booking_flow
from config import Config


class MongoCollections:
    ROOM_SESSION = "room_session"
    ROOM = "room"
    MESSAGE = "message"


class ChatRepository:
    """Mongo-backed repository for rooms, chat messages, and room session context."""

    @staticmethod
    def get_room_context(room_id: str) -> dict:
        try:
            doc = mongodb()[MongoCollections.ROOM_SESSION].find_one({"_id": room_id}) or {}
            doc.pop("_id", None)
            return doc
        except Exception:
            return {}

    @staticmethod
    def update_room_context(room_id: str, context_update: dict) -> None:
        try:
            now_utc = datetime.now(timezone.utc)
            mongodb()[MongoCollections.ROOM_SESSION].update_one(
                {"_id": room_id},
                {
                    "$set": {**context_update, "updated_at": now_utc},
                    "$setOnInsert": {"created_at": now_utc},
                },
                upsert=True,
            )
        except Exception:
            return

    @staticmethod
    def find_direct_room_by_mates(room_mate_uuids: list[str]) -> dict | None:
        return mongodb()[MongoCollections.ROOM].find_one(
            {
                "room_mates.uuid": {"$all": room_mate_uuids},
                "room_type": 0,
            }
        )

    @staticmethod
    def create_direct_room(room_mates: list[dict]) -> dict:
        room_id = str(uuid.uuid4())
        room_name = f"{room_mates[1]['name']}" if len(room_mates) == 2 else "Group conversation"
        now = datetime.now(timezone.utc).isoformat()

        new_room = {
            "room_id": room_id,
            "room_name": room_name,
            "room_type": 0,
            "created": now,
            "updated": now,
            "room_mates": room_mates,
            "active": True,
        }
        mongodb()[MongoCollections.ROOM].insert_one(new_room)

        return {
            "room_id": room_id,
            "room_name": room_name,
            "room_type": 0,
        }

    @staticmethod
    def create_room(room_mates: list[dict]) -> dict:
        room_details = {"room_type": 0}
        room_mate_uuids = sorted([mate["uuid"] for mate in room_mates])

        existing_room = ChatRepository.find_direct_room_by_mates(room_mate_uuids)
        if existing_room:
            room_details["room_id"] = existing_room["room_id"]
            room_details["room_name"] = existing_room["room_name"]
            return room_details

        return ChatRepository.create_direct_room(room_mates)

    @staticmethod
    def create_message(data: dict) -> dict:
        message = {
            "message_id": data.get("message_id"),
            "room_id": data.get("room_id"),
            "created": datetime.now(timezone.utc).isoformat(),
            "updated": datetime.now(timezone.utc).isoformat(),
            "sender_uuid": data.get("sender_uuid"),
            "sender_name": data.get("sender_name"),
            "message": data.get("message"),
            "delivery_status": 0,
            "delivery_status_trail": [],
            "active": True,
        }
        mongodb()[MongoCollections.MESSAGE].insert_one(message)
        message.pop("_id", None)
        return message

    @staticmethod
    def process_new_message(data: dict) -> None:
        ChatRepository.create_message(data)
        if data.get("is_chatting_to_admin"):
            chat_history = data.get("chat_history", [])
            bot_response = run_agentic_booking_flow(
                data.get("room_id"),
                data.get("message"),
                chat_history,
            )
            data["message_id"] = str(uuid.uuid4())
            data["message"] = bot_response
            data["sender_uuid"] = data.get("target_uuid")
            data["sender_name"] = data.get("target_name")
            ChatRepository.create_message(data)

    @staticmethod
    def get_recent_messages(room_id: str) -> list[dict]:
        query = {
            "active": True,
            "room_id": room_id,
        }
        return list(
            mongodb()[MongoCollections.MESSAGE]
            .find(query)
            .sort("created", -1)
            .limit(Config.CHAT_CONTEXT_LIMIT)
        )[::-1]

    @staticmethod
    def get_unread_messages_for_reader(room_id: str, reader_uuid: str, last_read_message_id: str = "") -> list[dict]:
        query = {
            "active": True,
            "room_id": room_id,
            "sender_uuid": {"$ne": reader_uuid},
            "delivery_status_trail": {
                "$not": {
                    "$elemMatch": {
                        "reader_uuid": reader_uuid,
                    }
                }
            },
        }

        if last_read_message_id:
            last_read_message = mongodb()[MongoCollections.MESSAGE].find_one(
                {"message_id": last_read_message_id}
            )
            if last_read_message:
                created_after = last_read_message.get("created")
                if created_after:
                    query["created"] = {"$gt": created_after}

        return list(
            mongodb()[MongoCollections.MESSAGE].find(query).sort("created", 1)
        )

    @staticmethod
    def update_delivery_status(reader_uuid: str, message_ids: list[str], delivery_status: int) -> None:
        trail_entry = {
            "reader_uuid": reader_uuid,
            "created": datetime.now(timezone.utc).isoformat(),
            "delivery_status": delivery_status,
        }
        for message_id in message_ids:
            mongodb()[MongoCollections.MESSAGE].update_one(
                {
                    "message_id": message_id,
                    "delivery_status_trail": {
                        "$not": {
                            "$elemMatch": {
                                "reader_uuid": reader_uuid,
                                "delivery_status": delivery_status,
                            }
                        }
                    },
                },
                {
                    "$push": {"delivery_status_trail": trail_entry},
                    "$set": {"delivery_status": delivery_status},
                },
            )
