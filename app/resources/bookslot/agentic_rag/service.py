from .workflow import run_agentic_booking_flow


def handle_user_input_agentic(room_id: str, user_input: str, chat_history: list[dict]) -> str:
    """Drop-in service function matching existing handler signature."""
    return run_agentic_booking_flow(room_id=room_id, user_input=user_input, chat_history=chat_history)
