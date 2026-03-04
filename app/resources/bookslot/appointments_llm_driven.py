"""Appointment Booking System
===========================

LLM-driven appointment booking with natural language understanding.
The LLM handles intent classification, date/time parsing, provider matching, 
and conversation flow while maintaining data integrity through context management.
"""

from langchain.agents import AgentExecutor, create_openai_functions_agent
from langchain.tools import StructuredTool
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import HumanMessage, AIMessage
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import logging
import json

from app.models.extensions import db
from config import Config

logger = logging.getLogger(__name__)

# Get current date for the system prompt
CURRENT_DATE = datetime.now(timezone.utc).strftime("%d-%B-%Y")

# Initialize shared LLM instances
_parser_llm = None
_provider_context_by_room = {}
_slot_context_by_room = {}
_active_room_id = None


def _room_key(room_id) -> str | None:
    if room_id is None:
        return None
    return str(room_id)


def _get_parser_llm():
    """Singleton LLM for parsing/normalization."""
    global _parser_llm
    if _parser_llm is None:
        _parser_llm = ChatOpenAI(model=Config.LLM_MODEL, temperature=0)
    return _parser_llm


def _strip_json_fence(content: str) -> str:
    """Remove markdown code fences from model output if present."""
    cleaned = (content or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    return cleaned


def _recover_slot_context_from_history(room_id: str) -> tuple[list, int | None, str | None]:
    """Recover provider/date/slots from persisted chat history using LLM.

    Returns:
        (slots_list, provider_id, requested_date)
    """
    try:
        chat_history = _get_chat_history_from_repo(room_id)
        if not chat_history:
            return [], None, None

        recent_messages = chat_history[-12:]
        transcript = "\n".join([
            f"{'assistant' if isinstance(msg, AIMessage) else 'user'}: {msg.content}"
            for msg in recent_messages
        ])

        llm = _get_parser_llm()
        prompt = f"""Extract appointment selection context from this conversation.

Conversation:
{transcript}

Return ONLY JSON with fields:
- provider_name: string or null
- requested_date: YYYY-MM-DD or null
- slots: array of objects with keys date (YYYY-MM-DD) and time (HH:MM:SS)

Rules:
- Use the latest assistant-shown slot list if present.
- Convert 12-hour times to HH:MM:SS.
- If uncertain, return null/empty values safely.

Example format:
{{"provider_name":"Dr. Nikhil Jadhav","requested_date":"2026-03-05","slots":[{{"date":"2026-03-05","time":"10:30:00"}}]}}"""

        response = llm.invoke(prompt)
        payload = json.loads(_strip_json_fence(response.content))

        provider_name = payload.get("provider_name")
        requested_date = payload.get("requested_date")
        slots = payload.get("slots") or []

        provider_id = None
        if provider_name:
            matches = get_matching_providers_llm(provider_name)
            if matches:
                provider_id = matches[0].get("id")

        return slots, provider_id, requested_date
    except Exception as error:
        logger.debug(f"Slot context recovery from history failed: {error}")
        return [], None, None

# =============================================================================
# Provider Matching
# =============================================================================

def get_matching_providers_llm(user_provider_name: str) -> list:
    """Use LLM to match user input against available providers."""
    cursor = db.cursor(dictionary=True)
    query = "SELECT id, name, service FROM service_providers"
    cursor.execute(query)
    all_providers = cursor.fetchall()
    cursor.close()
    
    if not all_providers:
        return []
    
    llm = _get_parser_llm()
    
    # Create provider list for LLM
    provider_list = "\n".join([
        f"- ID {p['id']}: {p['name']} ({p['service']})"
        for p in all_providers
    ])
    
    prompt = f"""Match the user's request to available providers.

User looking for: "{user_provider_name}"

Available providers:
{provider_list}

Return JSON array of matching provider IDs, ordered by relevance.
Examples:
- User "Nikhil" → [3] if Nikhil Jadhav exists
- User "cardiologist" → [2] if Priya does cardiology
- User "Sheetal" → [1] if exact match

Return ONLY JSON array like [3] or [3, 1] or [] if no match."""

    retry_prompt = f"""You must return the best provider IDs for this user query, even with spelling variation or partial names.

User query: "{user_provider_name}"

Available providers:
{provider_list}

Rules:
- Return ONLY a JSON array of provider IDs ordered by relevance.
- If uncertain, include the top likely matches instead of returning empty.
- Prefer semantic and phonetic closeness.

Output format examples: [3] or [2, 1] or []"""

    try:
        response = llm.invoke(prompt)
        content = _strip_json_fence(response.content)
        
        matched_ids = json.loads(content)
        
        # Return providers in matched order
        id_to_provider = {p['id']: p for p in all_providers}
        matched_providers = [id_to_provider[pid] for pid in matched_ids if pid in id_to_provider]
        if matched_providers:
            return matched_providers

        logger.debug("LLM returned no provider IDs, retrying with stricter prompt")
        retry_response = llm.invoke(retry_prompt)
        retry_content = _strip_json_fence(retry_response.content)

        retry_ids = json.loads(retry_content)
        retry_matches = [id_to_provider[pid] for pid in retry_ids if pid in id_to_provider]
        return retry_matches
        
    except Exception as e:
        logger.debug(f"LLM matching failed: {e}")
        return []


# =============================================================================
# Date/Time Normalization
# =============================================================================

def normalize_datetime_llm(value: str, value_type: str, current_date: str) -> str | None:
    """Use LLM to parse and normalize dates/times in any format.
    
    Args:
        value: User input like "tomorrow", "4 PM", "March 10th"
        value_type: "date" or "time"
        current_date: Current date for relative date resolution
        
    Returns:
        Normalized string: "YYYY-MM-DD" for dates, "HH:MM:SS" for times
    """
    if not value:
        return None
    
    llm = _get_parser_llm()
    
    if value_type == "date":
        prompt = f"""Today's date is {current_date}.

Convert this date expression to YYYY-MM-DD format:
"{value}"

Examples:
- "tomorrow" → "2026-03-05"
- "March 10th" → "2026-03-10"
- "next Friday" → "2026-03-06"
- "10/03/2026" → "2026-03-10"

Return ONLY the date in YYYY-MM-DD format, nothing else. If cannot parse, return "INVALID"."""
    else:  # time
        prompt = f"""Convert this time expression to HH:MM:SS (24-hour) format:
"{value}"

Examples:
- "4 PM" → "16:00:00"
- "10:30 AM" → "10:30:00"
- "16:00" → "16:00:00"
- "noon" → "12:00:00"

Return ONLY the time in HH:MM:SS format, nothing else. If cannot parse, return "INVALID"."""
    
    try:
        response = llm.invoke(prompt)
        normalized = response.content.strip()
        return None if normalized == "INVALID" else normalized
    except Exception as e:
        logger.error(f"LLM datetime normalization failed for {value}: {e}")
        return None


# =============================================================================
# Agent Tools
# =============================================================================

def get_available_slots(provider_id: int, date: str | None = None):
    """Fetch available slots from database.
    
    Returns JSON with slots data for the LLM to format and present.
    """
    global _active_room_id
    
    room_id_key = _room_key(_active_room_id)
    if room_id_key:
        room_context = _provider_context_by_room.get(room_id_key, {})
        primary_provider_id = room_context.get("primary_provider_id")
        
        if primary_provider_id and provider_id != primary_provider_id:
            return json.dumps({
                "error": "provider_mismatch",
                "message": f"Provider mismatch: requested {provider_id}, expected {primary_provider_id}"
            })
    
    cursor = db.cursor(dictionary=True)
    
    if date:
        query = """
            SELECT ss.available_date, ss.available_time, sp.name, sp.service
            FROM service_slots ss
            JOIN service_providers sp ON ss.provider_id = sp.id
            WHERE sp.id = %s AND ss.available_date = %s
            ORDER BY ss.available_date, ss.available_time
        """
        cursor.execute(query, (provider_id, date))
    else:
        query = """
            SELECT ss.available_date, ss.available_time, sp.name, sp.service
            FROM service_slots ss
            JOIN service_providers sp ON ss.provider_id = sp.id
            WHERE sp.id = %s
            ORDER BY ss.available_date, ss.available_time
        """
        cursor.execute(query, (provider_id,))
    
    slots = cursor.fetchall()
    cursor.close()
    
    slots_data = []
    for slot in slots:
        date_str = slot['available_date']
        if isinstance(date_str, str):
            date_str = str(date_str)
        else:
            date_str = slot['available_date'].strftime("%Y-%m-%d")
        
        time_obj = slot['available_time']
        if isinstance(time_obj, str):
            time_24h = time_obj
        else:
            total_seconds = int(time_obj.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            time_24h = f"{hours:02d}:{minutes:02d}:00"
        
        slots_data.append({
            "date": date_str,
            "time": time_24h
        })
    
    if room_id_key:
        if room_id_key not in _slot_context_by_room:
            _slot_context_by_room[room_id_key] = {}
        _slot_context_by_room[room_id_key]["slots"] = slots_data
        _slot_context_by_room[room_id_key]["provider_id"] = provider_id
        _slot_context_by_room[room_id_key]["requested_date"] = date
    
    return json.dumps({
        "provider_id": provider_id,
        "date_filter": date,
        "slots": slots_data,
        "count": len(slots_data)
    })

def check_availability(provider_id: int, date: str, time: str):
    """Check if a specific slot is available."""
    global _active_room_id
    
    room_id_key = _room_key(_active_room_id)
    if room_id_key:
        room_context = _provider_context_by_room.get(room_id_key, {})
        primary_provider_id = room_context.get("primary_provider_id")
        
        if primary_provider_id and provider_id != primary_provider_id:
            provider_id = primary_provider_id
            logger.info(f"Corrected provider_id to {provider_id} based on context")
    
    cursor = db.cursor(dictionary=True)
    query = """
        SELECT COUNT(*) as count 
        FROM service_slots ss
        JOIN service_providers sp ON ss.provider_id = sp.id
        WHERE sp.id = %s AND ss.available_date = %s AND ss.available_time = %s
    """
    cursor.execute(query, (provider_id, date, time))
    result = cursor.fetchone()
    cursor.close()
    
    return result["count"] > 0


# =============================================================================
# Agent Configuration
# =============================================================================

def create_appointment_agent_llm_driven(room_id: str) -> AgentExecutor:
    """Create appointment booking agent with LangChain and OpenAI function calling."""
    global _active_room_id
    _active_room_id = _room_key(room_id)
    
    # Initialize room context
    room_id_key = _room_key(room_id)
    if room_id_key not in _provider_context_by_room:
        _provider_context_by_room[room_id_key] = {}
    if room_id_key not in _slot_context_by_room:
        _slot_context_by_room[room_id_key] = {}
    
    llm = ChatOpenAI(model=Config.LLM_MODEL, temperature=0)
    
    system_prompt = f"""You are a helpful medical appointment booking assistant. Today is {CURRENT_DATE}.

Your role:
- Help users search for healthcare providers they want to see
- Use provider IDs returned in search_providers output (primary_provider_id / matches[*].id)
- Clarify the appointment date they prefer (if not mentioned, ask for it)
- Retrieve and display available appointment slots (numbered 1, 2, 3, etc.)
- When a user selects a numbered slot (e.g., "slot 1" or "option 2"), ALWAYS use the select_slot tool with that number
- Suggest alternative dates if their preferred date has no availability
- Be conversational, warm, and helpful

CRITICAL WORKFLOW:
1. User mentions a provider → call search_providers(provider_name)
2. Read provider_id from search_providers response (prefer primary_provider_id)
3. Ask user for preferred date
4. Call get_available_slots(provider_id, date) using the provider_id from step 2
5. Display slots numbered 1, 2, 3...
6. When user selects slot → call select_slot(slot_number) with that number
7. After select_slot success, acknowledge booking confirmation directly (no real booking API call needed)

Use the available tools: search_providers, get_available_slots, select_slot, check_availability.
Always confirm provider and date details with users before finalizing.
If you encounter any errors or data is missing, ask the user to clarify or try again."""
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad")
    ])
    
    # Define tools
    class ProviderInput(BaseModel):
        provider_name: str = Field(description="Doctor's name or specialty")
    
    class SlotsInput(BaseModel):
        provider_id: int = Field(description="Doctor's ID from provider search")
        date: str | None = Field(default=None, description="Appointment date in YYYY-MM-DD format (optional)")
    
    class AvailabilityInput(BaseModel):
        provider_id: int = Field(description="Doctor's ID")
        date: str = Field(description="Appointment date")
        time: str = Field(description="Appointment time")
    
    class SelectSlotInput(BaseModel):
        slot_number: int = Field(description="The slot number (1, 2, 3, etc.) that the user selected from the displayed list")
    
    def search_providers_wrapper(provider_name: str) -> str:
        """Search for matching healthcare providers. Returns JSON with provider IDs."""
        global _active_room_id
        
        matches = get_matching_providers_llm(provider_name)
        
        # Store primary provider in context if found
        room_id_key = _room_key(_active_room_id)
        if room_id_key and matches:
            if room_id_key not in _provider_context_by_room:
                _provider_context_by_room[room_id_key] = {}
            _provider_context_by_room[room_id_key]["primary_provider_id"] = matches[0]['id']
            _provider_context_by_room[room_id_key]["provider_name"] = matches[0]['name']
        
        # Return JSON with explicit primary provider details for next tool calls
        return json.dumps({
            "search_query": provider_name,
            "matches": [
                {"id": p['id'], "name": p['name'], "service": p['service']}
                for p in matches
            ],
            "count": len(matches),
            "primary_provider_id": matches[0]['id'] if matches else None,
            "primary_provider_name": matches[0]['name'] if matches else None
        })
    
    def get_slots_wrapper(provider_id: int, date: str | None = None) -> str:
        """Get available appointment slots."""
        global _active_room_id
        
        # Enforce provider continuity from room context if available
        room_id_key = _room_key(_active_room_id)
        if room_id_key:
            room_context = _provider_context_by_room.get(room_id_key, {})
            primary_provider_id = room_context.get("primary_provider_id")
            if primary_provider_id:
                provider_id = primary_provider_id

        result = get_available_slots(provider_id, date)
        
        try:
            result_data = json.loads(result)
        except:
            return result
        if room_id_key and "slots" in result_data:
            if room_id_key not in _slot_context_by_room:
                _slot_context_by_room[room_id_key] = {}
            _slot_context_by_room[room_id_key]["slots"] = result_data.get("slots", [])
            _slot_context_by_room[room_id_key]["provider_id"] = provider_id
            _slot_context_by_room[room_id_key]["requested_date"] = date
        
        return json.dumps({
            "provider_id": provider_id,
            "requested_date": date,
            "slots": result_data.get("slots", []),
            "total_slots": result_data.get("count", 0),
            "all_available_dates": _get_all_provider_dates(provider_id) if date and result_data.get("count", 0) == 0 else None
        })
    
    def check_availability_wrapper(provider_id: int, date: str, time: str) -> str:
        """Check if a specific slot is available."""
        normalized_date = normalize_datetime_llm(date, "date", CURRENT_DATE) or date
        normalized_time = normalize_datetime_llm(time, "time", CURRENT_DATE) or time
        
        is_available = check_availability(provider_id, normalized_date, normalized_time)
        
        return json.dumps({
            "provider_id": provider_id,
            "requested_date": date,
            "normalized_date": normalized_date,
            "requested_time": time,
            "normalized_time": normalized_time,
            "available": is_available
        })
    
    def select_slot_wrapper(slot_number: int) -> str:
        """Resolve a slot number to actual appointment details.
        
        When user selects "slot 1" or "option 2", this maps the number to 
        the actual provider_id, date, and time from the context.
        """
        global _active_room_id
        
        room_id_key = _room_key(_active_room_id)
        if not room_id_key or room_id_key not in _slot_context_by_room:
            return json.dumps({
                "error": "no_slots_available",
                "message": "No slots in context. Please ask for available slots first."
            })
        
        room_slots = _slot_context_by_room[room_id_key]
        slots_list = room_slots.get("slots", [])
        provider_id = room_slots.get("provider_id")
        requested_date = room_slots.get("requested_date")

        recovered_slots, recovered_provider_id, recovered_date = _recover_slot_context_from_history(room_id_key)
        if recovered_slots:
            room_slots["slots"] = recovered_slots
            slots_list = recovered_slots
        if recovered_provider_id:
            provider_id = recovered_provider_id
            room_slots["provider_id"] = recovered_provider_id
        if recovered_date:
            requested_date = recovered_date
            room_slots["requested_date"] = recovered_date

        if not slots_list:
            provider_context = _provider_context_by_room.get(room_id_key, {})
            provider_id = provider_id or provider_context.get("primary_provider_id")

            if provider_id and requested_date:
                recovered = get_available_slots(provider_id, requested_date)
                try:
                    recovered_data = json.loads(recovered)
                    recovered_slots = recovered_data.get("slots", [])
                    room_slots["slots"] = recovered_slots
                    room_slots["provider_id"] = provider_id
                    room_slots["requested_date"] = requested_date
                    slots_list = recovered_slots
                except Exception:
                    pass
        
        if not slots_list or slot_number < 1 or slot_number > len(slots_list):
            return json.dumps({
                "error": "invalid_slot_number",
                "message": f"Slot {slot_number} is not valid. Available slots: 1-{len(slots_list)}"
            })
        
        selected_slot = slots_list[slot_number - 1]
        
        return json.dumps({
            "slot_number": slot_number,
            "provider_id": provider_id,
            "date": selected_slot["date"],
            "time": selected_slot["time"],
            "formatted": f"{selected_slot['date']} at {selected_slot['time']}",
            "booking_acknowledged": True,
            "booking_status": "confirmed"
        })
    
    tools = [
        StructuredTool(
            name="search_providers",
            description="Search for healthcare providers/doctors by name or specialty. Returns matching providers that the user can choose from.",
            func=search_providers_wrapper,
            args_schema=ProviderInput
        ),
        StructuredTool(
            name="get_available_slots",
            description="Get available appointment slots for a provider. If no date is specified, this returns empty and you should ask the user for their preferred date.",
            func=get_slots_wrapper,
            args_schema=SlotsInput
        ),
        StructuredTool(
            name="check_availability",
            description="Check if a specific date/time slot is available for a provider.",
            func=check_availability_wrapper,
            args_schema=AvailabilityInput
        ),
        StructuredTool(
            name="select_slot",
            description="When user selects a numbered slot (e.g., 'slot 1', 'option 2'), use this tool to resolve the slot number to actual appointment details (provider_id, date, time).",
            func=select_slot_wrapper,
            args_schema=SelectSlotInput
        ),
    ]
    
    agent = create_openai_functions_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True)


def process_appointment_message_llm_driven(user_message: str, room_id: str, chat_history: list = None):
    """Process appointment booking request."""
    agent_executor = create_appointment_agent_llm_driven(room_id)
    
    if chat_history is None:
        chat_history = []
    
    try:
        response = agent_executor.invoke({
            "input": user_message,
            "chat_history": chat_history
        })
        return response.get("output", "")
    
    except Exception as e:
        logger.error(f"Error processing appointment message: {e}")
        return f"Encountered error: {str(e)}"


# =============================================================================
# Helper Functions
# =============================================================================

def _get_all_provider_dates(provider_id: int) -> list:
    """Get all unique dates with available slots for a provider."""
    try:
        cursor = db.cursor(dictionary=True)
        query = """
            SELECT DISTINCT ss.available_date
            FROM service_slots ss
            WHERE ss.provider_id = %s
            ORDER BY ss.available_date
        """
        cursor.execute(query, (provider_id,))
        results = cursor.fetchall()
        cursor.close()
        
        dates = []
        for r in results:
            if r['available_date']:
                date_str = str(r['available_date']) if isinstance(r['available_date'], str) else r['available_date'].strftime("%Y-%m-%d")
                dates.append(date_str)
        return dates
    except Exception as e:
        logger.error(f"Error fetching provider dates: {e}")
        return []


# =============================================================================
# Integration Functions (Compatible with existing system)
# =============================================================================

_agent_executor_cache = None

def _get_agent_executor_llm(room_id: str):
    """Get or create agent executor."""
    return create_appointment_agent_llm_driven(room_id)


def _get_chat_history_from_repo(room_id):
    """Fetch chat history from repository and convert to LangChain format."""
    from app.models.chat_repo import ChatRepo
    
    messages = ChatRepo.get_recent_messages(room_id)

    if not messages:
        return []

    current_user_uuid = messages[-1].get("sender_uuid")
    all_sender_uuids = [
        msg.get("sender_uuid")
        for msg in messages
        if msg.get("sender_uuid")
    ]
    unique_sender_uuids = list(dict.fromkeys(all_sender_uuids))

    ai_sender_uuid = None
    if current_user_uuid and len(unique_sender_uuids) == 2:
        for sender_uuid in unique_sender_uuids:
            if sender_uuid != current_user_uuid:
                ai_sender_uuid = sender_uuid
                break
    
    chat_history = []
    for msg in messages:
        content = msg.get('message', '')
        sender_uuid = msg.get("sender_uuid")
        if ai_sender_uuid and sender_uuid == ai_sender_uuid:
            chat_history.append(AIMessage(content=content))
        else:
            chat_history.append(HumanMessage(content=content))
    
    return chat_history


def handle_user_input(room_id, user_input):
    """Handle user input with the appointment booking agent."""
    global _active_room_id

    agent_executor = _get_agent_executor_llm(room_id)

    chat_history = _get_chat_history_from_repo(room_id)

    # Avoid duplicating current message
    if chat_history and isinstance(chat_history[-1], HumanMessage) and chat_history[-1].content == user_input:
        chat_history = chat_history[:-1]
    
    _active_room_id = _room_key(room_id)
    try:
        result = agent_executor.invoke({
            "input": user_input,
            "chat_history": chat_history
        })
        bot_response = result.get("output", "")
    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        bot_response = ""
    finally:
        _active_room_id = None

    return bot_response
