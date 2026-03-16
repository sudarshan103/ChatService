import json
from datetime import datetime, timezone

from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import AIMessage, HumanMessage
from langchain.tools import StructuredTool
from langchain_openai import ChatOpenAI

from config import Config
from app.models.schemas import (
    FindProvidersByServiceInput,
    KnowledgeSearchInput,
    ProviderInput,
    SelectSlotInput,
    SlotsInput,
)
from app.repositories.chat_repository import ChatRepository
from .agentic_booking_tools import (
    get_available_slots_agentic,
    search_providers_by_name,
    search_providers_by_service,
    search_knowledge_base,
)


def _convert_history(client_history: list[dict]) -> list:
    if not client_history:
        return []
    messages = []
    for item in client_history:
        role = item.get("role")
        content = item.get("content", "")
        if role == "assistant":
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))
    return messages


def _classify_user_intent(user_input: str, booking_confirmed: bool, llm: ChatOpenAI) -> str:
    """Classify user intent via LLM. Only called when booking_state is confirmed.

    Returns one of: confirm_booking, change_booking, other
    """
    context_str = "A booking has just been confirmed." if booking_confirmed else "No active booking."

    classification_prompt = (
        f"Current state: {context_str}\n"
        f'User message: "{user_input}"\n\n'
        "Classify the user's intent into exactly ONE category:\n"
        "- confirm_booking: affirming, confirming, or socially closing after a completed booking "
        "(yes, sure, sounds good, let's do it, absolutely, thanks, thank you, great, perfect, awesome, appreciated, got it, noted, etc.)\n"
        "- change_booking: wants to change, reschedule, or cancel the confirmed booking\n"
        "- other: anything else including new booking requests, questions, or follow-up information\n\n"
        "Respond with ONLY the category name, nothing else."
    )

    result = llm.bind(max_tokens=20).invoke(classification_prompt)
    return result.content.strip().lower().replace(" ", "_")


def _build_session_context_block(room_id: str) -> str:
    """Format current room context into a structured block injected into the agent system prompt."""
    context = ChatRepository.get_room_context(room_id)
    lines = []

    if context.get("active_provider_id"):
        locked = context.get("active_provider_locked", False)
        lines.append(
            f"Active provider: {context.get('active_provider_name')} "
            f"(provider_id={context.get('active_provider_id')}, service={context.get('active_service')}, "
            f"locked={'yes' if locked else 'no'})"
        )

    if context.get("awaiting_date_for_provider_id"):
        lines.append(
            f"Awaiting preferred date from user for provider_id={context.get('awaiting_date_for_provider_id')}"
        )

    slots = context.get("slots", [])
    if slots:
        requested_date = _format_date_for_user(context.get("requested_date")) or context.get("requested_date")
        lines.append(
            f"Pending slot options displayed to user: {len(slots)} slot(s) for "
            f"provider_id={context.get('provider_id')} on {requested_date}"
        )

    confirmed_bookings = context.get("confirmed_bookings") or []
    if confirmed_bookings:
        booking_lines = [
            (
                f"  {i + 1}. {b.get('provider_name')} on "
                f"{_format_date_for_user(b.get('date')) or b.get('date')} at {b.get('time')}"
            )
            for i, b in enumerate(confirmed_bookings)
        ]
        lines.append(f"Confirmed bookings this session:\n" + "\n".join(booking_lines))

    if not lines:
        return ""

    return "[Current Session State]\n" + "\n".join(f"- {line}" for line in lines)


def _pretty_slot_label(slot: dict) -> str:
    raw_date = str(slot.get("date") or "").strip()
    raw_time = str(slot.get("time") or "").strip()

    pretty_date = raw_date
    try:
        pretty_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        pass

    pretty_time = raw_time
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            pretty_time = datetime.strptime(raw_time, fmt).strftime("%I:%M%p").lower()
            break
        except Exception:
            continue

    return f"{pretty_date}, {pretty_time}"


def _format_date_for_user(value: str | None) -> str:
    """Render ISO dates for users as DD Mon YYYY; otherwise keep original text."""
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").strftime("%d %b %Y")
    except Exception:
        return raw_value


def _render_availability_reply(payload: dict, provider_name: str, provider_term: str) -> str | None:
    """Convert availability tool payload into a concise user-facing response."""
    error_code = payload.get("error")
    if error_code in {"invalid_date", "missing_date"}:
        return payload.get(
            "message",
            f"Please share your preferred date for {provider_name or f'the selected {provider_term}'}.",
        )

    slot_lines = payload.get("slot_lines") or []
    if slot_lines:
        date_filter = _format_date_for_user(payload.get("date_filter")) or "the selected date"
        slot_text = "\n".join(slot_lines)

        if payload.get("no_slots_on_requested_date"):
            original_date = _format_date_for_user(payload.get("original_date_requested")) or "that date"
            return (
                f"{provider_name} is not available on {original_date}. "
                f"Here are the next available slots on {date_filter}:\n"
                f"{slot_text}\n"
                "Please choose a slot number."
            )

        return (
            f"Here are the available slots for {provider_name} on {date_filter}:\n"
            f"{slot_text}\n"
            "Please choose a slot number."
        )

    if payload.get("all_available_dates") == []:
        return (
            f"I could not find any open slots for {provider_name} right now. "
            f"Would you like to try a different {provider_term}?"
        )

    return None


def _try_handle_awaiting_date(room_id: str, context: dict, user_input: str, provider_term: str) -> str | None:
    """Resolve pending date collection in one turn, returning a reply when handled."""
    awaiting_provider_id = context.get("awaiting_date_for_provider_id")
    if not awaiting_provider_id:
        return None

    tools_obj = BookingAgentTools(room_id)
    availability_result = tools_obj.get_provider_availability_slots(
        provider_id=awaiting_provider_id,
        date=user_input,
    )

    try:
        payload = json.loads(availability_result)
    except Exception:
        return availability_result

    provider_name = context.get("active_provider_name") or f"the selected {provider_term}"
    return _render_availability_reply(payload, provider_name, provider_term)


def _try_handle_booking_shortcircuit(
    room_id: str,
    context: dict,
    user_input: str,
    llm: ChatOpenAI,
    provider_term: str,
) -> str | None:
    """Handle one-turn acknowledgement after a confirmed booking."""
    if context.get("booking_state") != "confirmed":
        return None

    user_intent = _classify_user_intent(user_input, booking_confirmed=True, llm=llm)
    if user_intent == "confirm_booking":
        last_booking = (context.get("confirmed_bookings") or [{}])[-1]
        provider_name = last_booking.get("provider_name") or f"the selected {provider_term}"
        date = _format_date_for_user(last_booking.get("date"))
        time = last_booking.get("time")
        ChatRepository.update_room_context(room_id, {"booking_state": None})
        if date and time:
            return (
                f"Your appointment with {provider_name} on {date} at {time} is confirmed. "
                "If you need another appointment or have any changes, just let me know."
            )
        return "Your appointment is confirmed. If you need another appointment or have any changes, just let me know."

    # Any other intent (change request, new booking, follow-up question): clear
    # the transient confirmation flag and continue through the normal agent flow.
    ChatRepository.update_room_context(room_id, {"booking_state": None})
    return None


class BookingAgentTools:
    def __init__(self, room_id: str) -> None:
        self.room_id = room_id

    def find_providers_by_name(self, provider_name: str, limit: int = 5) -> str:
        result = search_providers_by_name(provider_name=provider_name, limit=limit)
        try:
            data = json.loads(result)
        except Exception:
            return result

        providers = data.get("providers", []) or []
        if len(providers) == 1:
            primary = providers[0]
            ChatRepository.update_room_context(
                self.room_id,
                {
                    "active_provider_id": primary.get("provider_id"),
                    "active_provider_name": primary.get("name"),
                    "active_service": primary.get("service"),
                    "active_provider_locked": True,
                },
            )
            ChatRepository.update_room_context(self.room_id, {"awaiting_date_for_provider_id": primary.get("provider_id")})
        elif len(providers) > 1:
            ChatRepository.update_room_context(
                self.room_id,
                {
                    "active_provider_id": None,
                    "active_provider_name": None,
                    "active_service": None,
                    "active_provider_locked": False,
                },
            )

        ChatRepository.update_room_context(self.room_id, {"provider_search_done": True})
        return result

    def find_providers_by_service(self, specialty: str, limit: int = 5) -> str:
        result = search_providers_by_service(service=specialty, limit=limit)
        try:
            data = json.loads(result)
        except Exception:
            return result

        resolved_service = data.get("resolved_service") or specialty
        providers = data.get("providers", []) or []
        if len(providers) == 1:
            primary = providers[0]
            ChatRepository.update_room_context(
                self.room_id,
                {
                    "active_provider_id": primary.get("provider_id"),
                    "active_provider_name": primary.get("name"),
                    "active_service": primary.get("service") or resolved_service,
                    "active_provider_locked": True,
                },
            )
            ChatRepository.update_room_context(self.room_id, {"awaiting_date_for_provider_id": primary.get("provider_id")})
        elif len(providers) > 1:
            ChatRepository.update_room_context(
                self.room_id,
                {
                    "active_provider_id": None,
                    "active_provider_name": None,
                    "active_service": resolved_service,
                    "active_provider_locked": False,
                },
            )

        ChatRepository.update_room_context(self.room_id, {"provider_search_done": True})
        return result

    def get_provider_availability_slots(self, provider_id: int, date: str | None = None) -> str:
        context = ChatRepository.get_room_context(self.room_id)
        active_provider_id = context.get("active_provider_id")
        active_provider_locked = bool(context.get("active_provider_locked"))

        if not context.get("provider_search_done") and not active_provider_id:
            return json.dumps({
                "error": "no_provider_search",
                "message": "No provider has been selected yet. Call find_providers_by_name or find_providers_by_service first, then retry get_provider_availability.",
            })

        normalized_date = (date or "").strip()
        awaiting_provider_id = active_provider_id if (active_provider_locked and active_provider_id) else provider_id
        if not normalized_date:
            ChatRepository.update_room_context(
                self.room_id,
                {
                    "awaiting_date_for_provider_id": awaiting_provider_id,
                    "slots": [],
                    "provider_id": None,
                    "requested_date": None,
                },
            )
            return json.dumps({
                "error": "missing_date",
                "message": "Preferred date is required before checking availability. Ask the user for a convenient date.",
            })

        ChatRepository.update_room_context(self.room_id, {"awaiting_date_for_provider_id": None})

        result = get_available_slots_agentic(provider_id=awaiting_provider_id, date=date)

        try:
            data = json.loads(result)
        except Exception:
            return result

        if date and data.get("count", 0) == 0 and data.get("next_available_date"):
            next_date = data["next_available_date"]
            fallback_result = get_available_slots_agentic(provider_id=awaiting_provider_id, date=next_date)
            try:
                fallback_data = json.loads(fallback_result)
                fallback_data["original_date_requested"] = date
                fallback_data["no_slots_on_requested_date"] = True
                fallback_slots = fallback_data.get("slots", []) or []
                fallback_data["slot_lines"] = [
                    f"{idx}. {_pretty_slot_label(slot)}"
                    for idx, slot in enumerate(fallback_slots, start=1)
                ]
                ChatRepository.update_room_context(
                    self.room_id,
                    {
                        "slots": fallback_slots,
                        "provider_id": awaiting_provider_id,
                        "requested_date": fallback_data.get("date_filter"),
                    },
                )
                return json.dumps(fallback_data)
            except Exception:
                pass

        slots = data.get("slots", []) or []
        data["slot_lines"] = [
            f"{idx}. {_pretty_slot_label(slot)}"
            for idx, slot in enumerate(slots, start=1)
        ]

        ChatRepository.update_room_context(
            self.room_id,
            {
                "slots": slots,
                "provider_id": awaiting_provider_id,
                "requested_date": data.get("date_filter"),
            },
        )
        return json.dumps(data)

    def select_slot(self, slot_number: int) -> str:
        room_context = ChatRepository.get_room_context(self.room_id)
        slots = room_context.get("slots", [])
        provider_id = room_context.get("provider_id")
        provider_name = room_context.get("active_provider_name")
        provider_term = Config.PROVIDER_DISPLAY_TERM

        if not slots or slot_number < 1 or slot_number > len(slots):
            return json.dumps({
                "error": "missing_slot_context",
                "message": f"Slot context not found. Please share the {provider_term} name and your preferred appointment date.",
            })

        selected_slot = slots[slot_number - 1]
        confirmed_bookings = room_context.get("confirmed_bookings") or []
        confirmed_bookings.append({
            "provider_id": provider_id,
            "provider_name": provider_name,
            "date": selected_slot.get("date"),
            "time": selected_slot.get("time"),
        })
        ChatRepository.update_room_context(
            self.room_id,
            {
                "confirmed_bookings": confirmed_bookings,
                # booking_state lives for exactly one user turn (to intercept social acknowledgements
                # cheaply without invoking the full agent), then it's always wiped.
                "booking_state": "confirmed",
                # Clear active context so the next booking starts fresh
                "active_provider_id": None,
                "active_provider_name": None,
                "active_service": None,
                "active_provider_locked": False,
                "slots": [],
                "provider_id": None,
                "requested_date": None,
                "awaiting_date_for_provider_id": None,
                "provider_search_done": False,
            },
        )
        return json.dumps(
            {
                "slot_number": slot_number,
                "provider_id": provider_id,
                "provider_name": provider_name,
                "date": selected_slot.get("date"),
                "time": selected_slot.get("time"),
                "formatted": (
                    f"{_format_date_for_user(selected_slot.get('date'))} "
                    f"at {selected_slot.get('time')}"
                ),
                "booking_status": "confirmed",
            }
        )


def create_booking_agent(room_id: str, llm: ChatOpenAI) -> AgentExecutor:
    """Agentic appointment booking flow using function tools and RAG knowledge base."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tools_obj = BookingAgentTools(room_id)

    provider_term = Config.PROVIDER_DISPLAY_TERM
    service_term = Config.SERVICE_DISPLAY_TERM
    persona = Config.BOOKING_ASSISTANT_PERSONA
    Provider_term = provider_term.capitalize()

    system_prompt = f"""You are an agentic {persona}. Today is {today}.

Workflow:
1. {Provider_term} named by user → call find_providers_by_name. Otherwise → call search_knowledge_base then find_providers_by_service.
2. Date is required before get_provider_availability. If missing, ask — include {provider_term} name/{service_term} if already known.
    If user gives a flexible date preference (for example: "anytime soon", "earliest available", "soonest", "first available"), treat it as valid date input and call get_provider_availability immediately.
3. Once {provider_term} and date are confirmed, MUST call get_provider_availability. Never invent or infer slot times.
4. Display slots as a numbered list, one slot per line.

provider_id rules:
- Only use provider_id from find_providers_by_name or find_providers_by_service results — never from search_knowledge_base, never guessed.
- Only mention a {provider_term} name to the user if that exact name appears in find_providers_by_name/find_providers_by_service tool output in the current turn/session context.
- Reuse active provider context unless a new search changes it.

Slot selection:
- User picks a numbered slot → always call select_slot.
- On success: booking is finalized. Do not ask "Would you like to proceed?". On affirmative follow-up, confirm and stop tool calls. Resume tools only for change/reschedule/cancel.
- On missing context error: ask for BOTH {provider_term} name and preferred date.

Slot display:
- Never re-show the slot list unless user explicitly asks again or requests a date/{provider_term} change; answer other questions directly.
- If user asks for slots beyond those shown: state no additional slots are available.

Availability results:
- no_slots_on_requested_date=true: clearly state the requested date is unavailable; show slot_lines for the next available date (date_filter). Never claim slots exist on the originally requested date.
- all_available_dates empty/null: inform the user and ask whether to try a different {provider_term}.

User-facing language:
- NEVER use the technical term "provider" in responses to the user. Always say "{provider_term}" instead.
- NEVER use the technical term "service_category" or "service_tags" in responses. Say "{service_term}" instead.
- When mentioning a date to the user, use this format exactly: DD Mon YYYY (example: 10 Apr 2026).
- Keep responses concise and friendly.

[Current Session State] block (if present):
- active provider locked=yes → reuse that provider_id; skip re-searching the same {provider_term}.
- Awaiting preferred date → call get_provider_availability immediately with that provider_id and the user's date.
- Pending slots → user may select without re-fetching.
- Confirmed bookings → finalized; start a completely fresh independent flow for each new {provider_term}/{service_term} concern.
"""

    prompt = ChatPromptTemplate.from_messages(
        [
            # Core agent instructions plus serialized room/session state for continuity.
            ("system", system_prompt + "\n{session_context}"),
            # Prior user/assistant turns converted into LangChain message objects.
            MessagesPlaceholder(variable_name="chat_history"),
            # The current user utterance being handled in this invocation.
            ("human", "{input}"),
            # Internal scratchpad where the agent records intermediate tool reasoning.
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )

    tools = [
        StructuredTool(
            name="search_knowledge_base",
            description=(
                "Semantic retrieval using OpenAI embeddings and pgvector search. "
                "Returns top service-level context docs with service_category and service_tags; "
                "does not return authoritative provider identities."
            ),
            func=search_knowledge_base,
            args_schema=KnowledgeSearchInput,
        ),
        StructuredTool(
            name="find_providers_by_name",
            description=f"Find {provider_term}s by name when the user directly mentions a {provider_term}.",
            func=tools_obj.find_providers_by_name,
            args_schema=ProviderInput,
        ),
        StructuredTool(
            name="find_providers_by_service",
            description=f"Find {provider_term}s by inferred {service_term}.",
            func=tools_obj.find_providers_by_service,
            args_schema=FindProvidersByServiceInput,
        ),
        StructuredTool(
            name="get_provider_availability",
            description=f"Fetch available slots for a {provider_term} for a user-provided date (natural language is allowed).",
            func=tools_obj.get_provider_availability_slots,
            args_schema=SlotsInput,
        ),
        StructuredTool(
            name="select_slot",
            description=(
                "When user selects a slot number (e.g., 'slot 1'), resolve it from room slot context. "
                f"If context is missing, this tool returns an error and you must ask for {provider_term} name and date."
            ),
            func=tools_obj.select_slot,
            args_schema=SelectSlotInput,
        ),
    ]

    agent = create_openai_functions_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True)


def run_agentic_booking_flow(room_id: str, user_input: str, chat_history: list[dict]) -> str:
    context = ChatRepository.get_room_context(room_id)
    llm = ChatOpenAI(model=Config.LLM_MODEL, temperature=0)
    provider_term = Config.PROVIDER_DISPLAY_TERM

    # Handle one-turn social acknowledgement after a confirmed booking without invoking the full agent.
    shortcircuit_reply = _try_handle_booking_shortcircuit(room_id, context, user_input, llm, provider_term)
    if shortcircuit_reply:
        return shortcircuit_reply

    # Resolve pending date collection directly from the current user message.
    direct_reply = _try_handle_awaiting_date(room_id, context, user_input, provider_term)
    if direct_reply:
        return direct_reply

    session_context = _build_session_context_block(room_id)
    executor = create_booking_agent(room_id=room_id, llm=llm)
    result = executor.invoke({
        "input": user_input,
        "chat_history": _convert_history(chat_history),
        "session_context": session_context,
    })
    return result.get("output", "")
