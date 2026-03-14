import json
import re
from datetime import datetime, timezone

from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import AIMessage, HumanMessage
from langchain.tools import StructuredTool
from langchain_openai import ChatOpenAI

from config import Config
from app.models.extensions import mongodb
from app.models.mongo_utils import MongoCollections
from app.models.schemas import FindDoctorsBySpecialtyInput, MedicalKnowledgeInput, ProviderInput, SelectSlotInput, SlotsInput
from .tools import (
    _normalize_requested_date,
    find_doctors_by_name,
    find_doctors_by_specialty,
    get_doctor_availability,
    search_medical_knowledge,
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


def _get_room_context(room_id: str) -> dict:
    try:
        doc = mongodb()[MongoCollections.ROOM_SESSION].find_one({"_id": room_id}) or {}
        doc.pop("_id", None)
        return doc
    except Exception:
        return {}


def _set_room_context(room_id: str, context_update: dict) -> None:
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


def _get_slot_context(room_id: str) -> dict:
    context = _get_room_context(room_id)
    return {
        "slots": context.get("slots", []),
        "provider_id": context.get("provider_id"),
        "requested_date": context.get("requested_date"),
    }


def _set_slot_context(room_id: str, slots: list, provider_id: int | None, requested_date: str | None) -> None:
    _set_room_context(
        room_id,
        {
            "slots": slots,
            "provider_id": provider_id,
            "requested_date": requested_date,
        },
    )


def _set_active_provider_context(
    room_id: str,
    provider_id: int | None,
    provider_name: str | None,
    specialty: str | None,
    provider_locked: bool,
) -> None:
    _set_room_context(
        room_id,
        {
            "active_provider_id": provider_id,
            "active_provider_name": provider_name,
            "active_specialty": specialty,
            "active_provider_locked": provider_locked,
        },
    )


def create_agentic_booking_agent(room_id: str) -> AgentExecutor:
    """Agentic medical booking flow using function tools and RAG."""
    llm = ChatOpenAI(model=Config.LLM_MODEL, temperature=0)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    system_prompt = f"""You are an agentic medical booking assistant. Today is {today}.

Workflow:
1. If user mentions a doctor name, call find_doctors_by_name first.
2. Otherwise, call search_medical_knowledge and then find_doctors_by_specialty.
3. Ask for preferred date if missing or ambiguous.
4. Call get_doctor_availability only after doctor and date are confirmed.
5. Present slots as a concise numbered list.

Rules:
- Use tool outputs as evidence for specialty and doctor recommendation.
- Keep responses concise and patient-friendly.
- Never expose raw JSON in final user text.
- Date is mandatory before get_doctor_availability. If user did not provide a date, ask for it first.
- If a specific doctor is already identified, include that doctor's name and specialty when asking for the date.
- Once a doctor is identified and the user provides date text, MUST call get_doctor_availability before responding. Never invent or infer slot times/dates without tool output.
- Never use provider_id from search_medical_knowledge output directly.
- Use provider_id only from find_doctors_by_name or find_doctors_by_specialty results.
- Never guess provider_id. Reuse active provider context unless a new doctor search changes it.
- When user selects a numbered option (e.g., "slot 1"), always call select_slot.
- After select_slot succeeds, treat the booking as finalized for this flow. Do not ask "Would you like to proceed?".
- If user sends an affirmative after finalized booking (e.g., "yes"), acknowledge confirmation and end the flow without calling more tools.
- Only resume tool calls after finalized booking if user asks to change/reschedule/cancel.
- If select_slot returns missing context, ask for BOTH doctor name and preferred date.
- If slot options were already shown and the user asks a different question without selecting a slot number, answer that question directly and do not repeat the same slot list.
- Only show slot options again if the user explicitly asks to see slots again or asks for a date/doctor change.
- If slot options are already shown and user asks for alternative slots beyond those options, respond gracefully that no additional slots are available right now. Do not repeat the same slot list.
- If get_doctor_availability returns no_slots_on_requested_date=true, explain requested date had no slots and show next available slots from tool output.
- If get_doctor_availability returns no_slots_on_requested_date=true, NEVER say slots are available on the requested date. Clearly state requested date is unavailable and slot_lines are for the next available date (date_filter).
- If there are no slots on any date (all_available_dates is empty or null), inform clearly and ask whether to try another doctor.
- When displaying slots, always show a numbered list with exactly one slot per line. Do not combine multiple slots in one sentence.
"""

    def find_doctors_by_name_wrapper(provider_name: str, limit: int = 5) -> str:
        result = find_doctors_by_name(provider_name=provider_name, limit=limit)
        try:
            data = json.loads(result)
        except Exception:
            return result

        doctors = data.get("doctors", []) or []
        if len(doctors) == 1:
            primary = doctors[0]
            _set_active_provider_context(
                room_id=room_id,
                provider_id=primary.get("provider_id"),
                provider_name=primary.get("name"),
                specialty=primary.get("specialty"),
                provider_locked=True,
            )
            _set_room_context(room_id, {"awaiting_date_for_provider_id": primary.get("provider_id")})
        elif len(doctors) > 1:
            _set_active_provider_context(
                room_id=room_id,
                provider_id=None,
                provider_name=None,
                specialty=None,
                provider_locked=False,
            )

        _set_room_context(room_id, {"doctor_search_done": True})
        return result

    def find_doctors_by_specialty_wrapper(specialty: str, limit: int = 5) -> str:
        result = find_doctors_by_specialty(specialty=specialty, limit=limit)
        try:
            data = json.loads(result)
        except Exception:
            return result

        doctors = data.get("doctors", []) or []
        if len(doctors) == 1:
            primary = doctors[0]
            _set_active_provider_context(
                room_id=room_id,
                provider_id=primary.get("provider_id"),
                provider_name=primary.get("name"),
                specialty=primary.get("specialty"),
                provider_locked=True,
            )
            _set_room_context(room_id, {"awaiting_date_for_provider_id": primary.get("provider_id")})
        elif len(doctors) > 1:
            _set_active_provider_context(
                room_id=room_id,
                provider_id=None,
                provider_name=None,
                specialty=specialty,
                provider_locked=False,
            )

        # Mark that a doctor search has been performed for this room session.
        _set_room_context(room_id, {"doctor_search_done": True})
        return result

    def get_doctor_availability_wrapper(provider_id: int, date: str | None = None) -> str:
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

        context = _get_room_context(room_id)
        active_provider_id = context.get("active_provider_id")
        active_provider_locked = bool(context.get("active_provider_locked"))

        # Guard: prevent provider_id hallucination from RAG results by requiring a prior doctor search.
        if not context.get("doctor_search_done") and not active_provider_id:
            return json.dumps({
                "error": "no_doctor_search",
                "message": "No doctor has been selected yet. Call find_doctors_by_name or find_doctors_by_specialty first, then retry get_doctor_availability.",
            })

        # Strict rule: do not fetch availability until the user provides a preferred date.
        normalized_date = (date or "").strip()
        if not normalized_date:
            awaiting_provider_id = active_provider_id if (active_provider_locked and active_provider_id) else provider_id
            _set_room_context(room_id, {"awaiting_date_for_provider_id": awaiting_provider_id})
            # Clear stale slot context so follow-up date messages are not treated as pending-slot chatter.
            _set_slot_context(room_id=room_id, slots=[], provider_id=awaiting_provider_id, requested_date=None)
            return json.dumps(
                {
                    "error": "missing_date",
                    "message": "Preferred date is required before checking availability. Ask the user for a convenient date.",
                }
            )

        # Date was provided; clear awaiting-date marker.
        _set_room_context(room_id, {"awaiting_date_for_provider_id": None})

        resolved_provider_id = provider_id
        # If only one provider was previously recommended, keep that provider to avoid ID drift.
        if active_provider_locked and active_provider_id:
            resolved_provider_id = active_provider_id

        result = get_doctor_availability(provider_id=resolved_provider_id, date=date)

        try:
            data = json.loads(result)
        except Exception:
            return result

        # Auto-fallback: if no slots on the specific requested date, immediately fetch next available date.
        if date and data.get("count", 0) == 0 and data.get("next_available_date"):
            next_date = data["next_available_date"]
            fallback_result = get_doctor_availability(provider_id=resolved_provider_id, date=next_date)
            try:
                fallback_data = json.loads(fallback_result)
                fallback_data["original_date_requested"] = date
                fallback_data["no_slots_on_requested_date"] = True
                fallback_slots = fallback_data.get("slots", []) or []
                fallback_data["slot_lines"] = [
                    f"{idx}. {_pretty_slot_label(slot)}"
                    for idx, slot in enumerate(fallback_slots, start=1)
                ]
                _set_slot_context(
                    room_id=room_id,
                    slots=fallback_slots,
                    provider_id=resolved_provider_id,
                    requested_date=fallback_data.get("date_filter"),
                )
                return json.dumps(fallback_data)
            except Exception:
                pass

        slots = data.get("slots", []) or []
        data["slot_lines"] = [
            f"{idx}. {_pretty_slot_label(slot)}"
            for idx, slot in enumerate(slots, start=1)
        ]

        _set_slot_context(
            room_id=room_id,
            slots=slots,
            provider_id=resolved_provider_id,
            requested_date=data.get("date_filter"),
        )
        return json.dumps(data)

    def select_slot_wrapper(slot_number: int) -> str:
        slot_context = _get_slot_context(room_id)
        slots = slot_context.get("slots", [])
        provider_id = slot_context.get("provider_id")
        room_context = _get_room_context(room_id)
        provider_name = room_context.get("active_provider_name")

        if not slots or slot_number < 1 or slot_number > len(slots):
            return json.dumps(
                {
                    "error": "missing_slot_context",
                    "message": "Slot context not found. Please share doctor name and preferred appointment date.",
                }
            )

        selected_slot = slots[slot_number - 1]
        # Persist terminal booking state so post-confirmation affirmatives do not re-trigger tool calls.
        _set_room_context(
            room_id,
            {
                "booking_state": "confirmed",
                "selected_provider_id": provider_id,
                "selected_provider_name": provider_name,
                "selected_date": selected_slot.get("date"),
                "selected_time": selected_slot.get("time"),
            },
        )
        return json.dumps(
            {
                "slot_number": slot_number,
                "provider_id": provider_id,
                "provider_name": provider_name,
                "date": selected_slot.get("date"),
                "time": selected_slot.get("time"),
                "formatted": f"{selected_slot.get('date')} at {selected_slot.get('time')}",
                "booking_status": "confirmed",
            }
        )

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )

    tools = [
        StructuredTool(
            name="search_medical_knowledge",
            description=(
                "Semantic retrieval using OpenAI embeddings and psycopg2 pgvector search. "
                "Returns top medical context docs with specialty, provider_id, and doctor_name."
            ),
            func=search_medical_knowledge,
            args_schema=MedicalKnowledgeInput,
        ),
        StructuredTool(
            name="find_doctors_by_name",
            description="Find doctors/providers by doctor name when the user directly mentions a doctor.",
            func=find_doctors_by_name_wrapper,
            args_schema=ProviderInput,
        ),
        StructuredTool(
            name="find_doctors_by_specialty",
            description="Find doctors/providers by inferred specialty.",
            func=find_doctors_by_specialty_wrapper,
            args_schema=FindDoctorsBySpecialtyInput,
        ),
        StructuredTool(
            name="get_doctor_availability",
            description="Fetch available provider slots for a user-provided date (natural language is allowed).",
            func=get_doctor_availability_wrapper,
            args_schema=SlotsInput,
        ),
        StructuredTool(
            name="select_slot",
            description=(
                "When user selects a slot number (e.g., 'slot 1'), resolve it from room slot context. "
                "If context is missing, this tool returns an error and you must ask for doctor name and date."
            ),
            func=select_slot_wrapper,
            args_schema=SelectSlotInput,
        ),
    ]

    agent = create_openai_functions_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True)


def run_agentic_booking_flow(room_id: str, user_input: str, chat_history: list[dict]) -> str:
    routed_input = user_input
    lowered_input = (user_input or "").strip().lower()
    context = _get_room_context(room_id)
    slot_context = _get_slot_context(room_id)
    has_pending_slots = bool(slot_context.get("slots"))

    def _is_affirmative(text: str) -> bool:
        return text in {"yes", "y", "ok", "okay", "sure", "confirm", "confirmed", "go ahead", "please do"}

    def _is_change_intent(text: str) -> bool:
        return any(word in text for word in ["change", "reschedule", "cancel", "another", "different", "modify"])

    def _is_slot_selection(text: str) -> bool:
        compact = text.strip().lower()
        if re.fullmatch(r"\d+", compact):
            return True
        if re.search(r"\b(slot|option)\s*\d+\b", compact):
            return True
        return False

    def _asks_slots_again(text: str) -> bool:
        return any(phrase in text for phrase in ["show slots", "show options", "available slots", "slot options", "repeat slots"])

    awaiting_date_provider_id = context.get("awaiting_date_for_provider_id")
    # If previous turn asked for date, force the next user message through availability tool with that provider.
    if awaiting_date_provider_id and not _is_change_intent(lowered_input):
        routed_input = (
            f"A provider is already selected (provider_id={awaiting_date_provider_id}) and the user has now provided date text: '{user_input}'. "
            "Call get_doctor_availability with this provider_id and the user's date text exactly as provided. "
            "Do not call find_doctors_by_name or find_doctors_by_specialty in this turn."
        )

    # Short-circuit finalized bookings: avoid unnecessary tool calls on post-confirmation affirmatives.
    if context.get("booking_state") == "confirmed":
        if _is_change_intent(lowered_input):
            _set_room_context(
                room_id,
                {
                    "booking_state": None,
                    "selected_provider_id": None,
                    "selected_provider_name": None,
                    "selected_date": None,
                    "selected_time": None,
                    "slots": [],
                    "provider_id": None,
                    "requested_date": None,
                },
            )
        elif _is_affirmative(lowered_input):
            selected_provider_name = context.get("selected_provider_name") or context.get("active_provider_name") or "the selected doctor"
            selected_date = context.get("selected_date")
            selected_time = context.get("selected_time")
            if selected_date and selected_time:
                return (
                    f"Your appointment with {selected_provider_name} on {selected_date} at {selected_time} is confirmed. "
                    "If you want to reschedule or cancel, let me know."
                )
            return "Your appointment is confirmed. If you want to reschedule or cancel, let me know."
        else:
            # Start a fresh flow after previous booking completion.
            _set_room_context(
                room_id,
                {
                    "booking_state": None,
                    "selected_provider_id": None,
                    "selected_provider_name": None,
                    "selected_date": None,
                    "selected_time": None,
                    "awaiting_date_for_provider_id": None,
                    "doctor_search_done": False,
                    "active_provider_id": None,
                    "active_provider_name": None,
                    "active_specialty": None,
                    "active_provider_locked": False,
                    "slots": [],
                    "provider_id": None,
                    "requested_date": None,
                },
            )
            context = _get_room_context(room_id)
            slot_context = _get_slot_context(room_id)
            has_pending_slots = bool(slot_context.get("slots"))
            awaiting_date_provider_id = context.get("awaiting_date_for_provider_id")

    # If slots are pending and user did not select one, answer their follow-up directly without repeating slots.
    if not awaiting_date_provider_id and has_pending_slots and not _is_slot_selection(lowered_input) and not _asks_slots_again(lowered_input) and not _is_change_intent(lowered_input):
        routed_input = (
            "The user currently has pending slot options, but they did not select a slot number in this turn. "
            "Answer the user's question directly and gracefully. Do NOT call get_doctor_availability and do NOT repeat the same slot list unless the user explicitly asks for slots again. "
            f"Original user input: {user_input}"
        )

    # Deterministic pre-routing: if user directly mentions a doctor name, seed provider context first.
    doctor_mentions = re.findall(r"\bdr\.?\s+([a-z][a-z\s'-]{1,40})", (user_input or "").lower())
    for mention in doctor_mentions:
        candidate = " ".join(mention.split()[:3]).strip()
        if not candidate:
            continue

        try:
            lookup = json.loads(find_doctors_by_name(provider_name=candidate, limit=5))
        except Exception:
            continue

        doctors = lookup.get("doctors", []) or []
        if not doctors:
            continue

        if len(doctors) == 1:
            primary = doctors[0]
            _set_active_provider_context(
                room_id=room_id,
                provider_id=primary.get("provider_id"),
                provider_name=primary.get("name"),
                specialty=primary.get("specialty"),
                provider_locked=True,
            )
            _set_room_context(room_id, {"doctor_search_done": True})
            routed_input = (
                f"The user directly requested doctor '{primary.get('name')}' (provider_id={primary.get('provider_id')}). "
                f"When asking for preferred appointment date, explicitly mention doctor name and specialty: "
                f"'{primary.get('name')}' ({primary.get('specialty')}). "
                "If the original user request already includes date text (including natural language or minor typos), use that date text directly in get_doctor_availability instead of asking again. "
                "If no date text is present, ask for preferred date first. "
                "Then call get_doctor_availability for this provider. "
                "Do not call find_doctors_by_specialty for this turn. "
                f"Original user request: {user_input}"
            )
            break

        _set_active_provider_context(
            room_id=room_id,
            provider_id=None,
            provider_name=None,
            specialty=None,
            provider_locked=False,
        )
        _set_room_context(room_id, {"doctor_search_done": True})
        routed_input = (
            "User mentioned a doctor name but multiple matches were found. "
            "Call find_doctors_by_name to present matching doctors and ask user to pick one. "
            f"Original user request: {user_input}"
        )
        break

    executor = create_agentic_booking_agent(room_id=room_id)
    result = executor.invoke({"input": routed_input, "chat_history": _convert_history(chat_history)})
    return result.get("output", "")
