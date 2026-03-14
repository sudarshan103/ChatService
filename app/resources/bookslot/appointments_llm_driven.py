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
from datetime import datetime, timezone, timedelta, time as dt_time
import logging
import json

from app.models.extensions import db
from app.models.schemas import ProviderInput, SelectSlotInput, SlotsInput
from config import Config


from app.models.extensions import mongodb
from app.models.mongo_utils import MongoCollections

logger = logging.getLogger(__name__)

# Initialize shared LLM instances
_parser_llm = None

def _get_llm():
    """Singleton LLM for parsing/normalization."""
    global _parser_llm
    if _parser_llm is None:
        _parser_llm = ChatOpenAI(model=Config.LLM_MODEL, temperature=0)
    return _parser_llm

def _get_current_date() -> str:
    """Get current date dynamically (not static)."""
    return datetime.now(timezone.utc).strftime("%d-%B-%Y")


def _get_room_context(room_id: str) -> dict:
    """Get room context from MongoDB.
    
    Args:
        room_id: Unique room identifier
        
    Returns:
        Dict with 'provider_id', 'provider_name', etc. or empty dict if not found
    """
    try:
        doc = mongodb()[MongoCollections.ROOM_SESSION].find_one({"_id": room_id})
        if doc:
            # Remove internal MongoDB fields
            doc.pop('_id', None)
            doc.pop('created_at', None)
            doc.pop('updated_at', None)
            return doc
    except Exception as e:
        logger.debug(f"Error reading room context from MongoDB: {e}")
    return {}


def _set_room_context(room_id: str, context_update: dict) -> None:
    """Set/update room context in MongoDB.
    
    Args:
        room_id: Unique room identifier
        context_update: Dict with context fields to update
    """
    try:
        collection = mongodb()[MongoCollections.ROOM_SESSION]
        now_utc = datetime.now(timezone.utc)
        collection.update_one(
            {"_id": room_id},
            {
                "$set": {
                    **context_update,
                    "updated_at": now_utc
                },
                "$setOnInsert": {
                    "created_at": now_utc
                }
            },
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error writing room context to MongoDB: {e}")


def _get_slot_context(room_id: str) -> dict:
    """Get slot context (slots, provider_id, requested_date) from MongoDB."""
    context = _get_room_context(room_id)
    return {
        "slots": context.get("slots", []),
        "provider_id": context.get("provider_id"),
        "requested_date": context.get("requested_date")
    }


def _set_slot_context(room_id: str, slots: list, provider_id: int | None, requested_date: str | None) -> None:
    """Set slot context in MongoDB."""
    _set_room_context(room_id, {
        "slots": slots,
        "provider_id": provider_id,
        "requested_date": requested_date
    })

def _extract_doctor_name_llm(user_input: str) -> str | None:
    """Use LLM to extract and normalize doctor name from user input.
    
    Removes prefixes like 'Mr', 'Dr', 'Doctor', 'Ms', 'Mrs' and extracts
    the actual name for efficient database searching.
    
    Args:
        user_input: User's query like "Dr. Nikhil Jadhav" or "I want to see doctor Smith"
        
    Returns:
        Normalized name or None if unable to extract
    """
    if not user_input or not user_input.strip():
        return None
    
    llm = _get_llm()
    
    prompt = f"""You are a name extraction specialist. Your task is to extract the doctor/provider's name from user input.

STRICT INSTRUCTIONS:
1. Remove all titles: Dr., Dr, Doctor, Mr., Mr, Ms., Ms, Mrs., Mrs, Prof., Prof, Professor, etc.
2. Extract ONLY the person's name (first name, last name, or both)
3. Return the extracted name with no extra words, no periods, no commas
4. If ONLY a title exists with no actual name (e.g., "I need a cardiologist"), return "NONE"

INPUT TEXT: "{user_input}"

PROCESS:
- Does the input have a person's name? YES/NO
- What is that name (without titles)?
- Return the final answer

EXAMPLES (follow these patterns exactly):
Input: "Dr. Nikhil Jadhav" → Output: "Nikhil Jadhav"
Input: "dr nikhil" → Output: "Nikhil"
Input: "Dr Nikhil" → Output: "Nikhil"
Input: "doctor nikhil jadhav" → Output: "Nikhil Jadhav"
Input: "I want Dr Priya" → Output: "Priya"
Input: "doctor smith" → Output: "smith"
Input: "Dr Priya Sharma" → Output: "Priya Sharma"
Input: "Sheetal" → Output: "Sheetal"
Input: "dr sheetal" → Output: "Sheetal"
Input: "Professor Kumar" → Output: "Kumar"
Input: "mr jadhav" → Output: "jadhav"
Input: "ms gupta please" → Output: "gupta"
Input: "mrs sharma" → Output: "sharma"
Input: "I need a cardiologist" → Output: "NONE"
Input: "find orthopedic doctor" → Output: "NONE"
Input: "best neurologist" → Output: "NONE"

FINAL ANSWER (return ONLY the name or NONE, nothing else):"""
    
    try:
        response = llm.invoke(prompt)
        name = response.content.strip()
        # Only return if not empty and not NONE
        if name and name.upper() != "NONE":
            return name
        return None
    except Exception as e:
        logger.debug(f"LLM name extraction failed: {e}")
        return None


def _convert_client_history_to_langchain(client_history: list) -> list:
    """Convert client chat history format to LangChain message objects.
    
    Args:
        client_history: List of dicts with format:
            [{"role": "user" | "assistant", "content": "message text"}, ...]
    
    Returns:
        List of LangChain HumanMessage/AIMessage objects
    """
    if not client_history:
        return []
    
    return [
        AIMessage(content=msg["content"]) if msg["role"] == "assistant"
        else HumanMessage(content=msg["content"])
        for msg in client_history
    ]


# =============================================================================
# Provider Matching
# =============================================================================

def get_matching_providers_llm(user_provider_name: str) -> list:
    """Match user input against providers using efficient database query.
    
    Strategy:
    1. Extract actual name from user input (e.g., "Dr. Nikhil" → "Nikhil")
    2. Query database for providers where name LIKE extracted_name (case-insensitive)
    3. Avoid loading all providers into memory - use database-level filtering
    
    Args:
        user_provider_name: User's query (can include titles, specialty, or name)
        
    Returns:
        List of matching providers as dicts with id, name, service keys
    """
    # First, try LLM to extract the actual name from user input
    extracted_name = _extract_doctor_name_llm(user_provider_name)
    
    cursor = db.cursor()
    
    # If LLM extracted a name, search by name similarity
    if extracted_name and extracted_name.lower() != "none":
        # Use LIKE query for efficient database-level filtering
        # Match exact, prefix, or fuzzy patterns
        search_pattern = f"%{extracted_name}%"
        
        query = """
            SELECT id, name, service FROM service_providers
            WHERE name ILIKE %s
            ORDER BY 
                CASE 
                    WHEN name ILIKE %s THEN 0  -- Exact match first
                    WHEN name ILIKE %s THEN 1  -- Prefix match
                    ELSE 2  -- Contains match
                END,
                name ASC
            LIMIT 20
        """
        
        exact_pattern = extracted_name
        prefix_pattern = f"{extracted_name}%"
        
        try:
            cursor.execute(query, (search_pattern, exact_pattern, prefix_pattern))
            results = cursor.fetchall()
            cursor.close()
            
            if results:
                return results
            cursor = db.cursor()
        except Exception as e:
            logger.debug(f"Database search failed: {e}")
            cursor.close()
            cursor = db.cursor()
    
    # Fallback: if extraction failed or no results, try specialty/service search
    try:
        search_pattern = f"%{user_provider_name}%"
        query = """
            SELECT id, name, service FROM service_providers
            WHERE name ILIKE %s OR service ILIKE %s
            ORDER BY name ASC
            LIMIT 20
        """
        
        cursor.execute(query, (search_pattern, search_pattern))
        results = cursor.fetchall()
        cursor.close()
        
        return results if results else []
    
    except Exception as e:
        logger.debug(f"Provider matching failed: {e}")
        if cursor:
            cursor.close()
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
    
    llm = _get_llm()
    
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

def get_available_slots(provider_id: int, room_id: str | None = None, date: str | None = None):
    """Fetch available slots from database.
    
    Returns JSON with slots data for the LLM to format and present.
    """
    cursor = db.cursor()
    
    normalized_date = date
    if normalized_date:
        normalized_date = str(normalized_date).strip()
        if "T" in normalized_date:
            normalized_date = normalized_date.split("T", 1)[0]

    if normalized_date:
        query = """
            SELECT ss.available_date, ss.available_time, sp.name, sp.service
            FROM service_slots ss
            JOIN service_providers sp ON ss.provider_id = sp.id
            WHERE sp.id = %s AND DATE(ss.available_date) = %s
            ORDER BY ss.available_date, ss.available_time
        """
        cursor.execute(query, (provider_id, normalized_date))
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
            time_24h = f"{time_obj}:00" if len(time_obj) == 5 else time_obj
        elif isinstance(time_obj, dt_time):
            time_24h = time_obj.strftime("%H:%M:%S")
        elif isinstance(time_obj, timedelta):
            total_seconds = int(time_obj.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            time_24h = f"{hours:02d}:{minutes:02d}:00"
        else:
            time_24h = str(time_obj)
        
        slots_data.append({
            "date": date_str,
            "time": time_24h
        })
    
    if room_id:
        _set_slot_context(room_id, slots_data, provider_id, normalized_date)
    
    return json.dumps({
        "provider_id": provider_id,
        "date_filter": normalized_date,
        "slots": slots_data,
        "count": len(slots_data)
    })

def check_availability(provider_id: int, room_id: str | None = None, date: str | None = None, time: str | None = None):
    """Check if a specific slot is available."""
    normalized_date = date
    if normalized_date:
        normalized_date = str(normalized_date).strip()
        if "T" in normalized_date:
            normalized_date = normalized_date.split("T", 1)[0]

    cursor = db.cursor()
    query = """
        SELECT COUNT(*) as count 
        FROM service_slots ss
        JOIN service_providers sp ON ss.provider_id = sp.id
        WHERE sp.id = %s AND DATE(ss.available_date) = %s AND ss.available_time = %s
    """
    cursor.execute(query, (provider_id, normalized_date, time))
    result = cursor.fetchone()
    cursor.close()
    
    return result["count"] > 0


# =============================================================================
# Agent Configuration
# =============================================================================

def create_langchain_agent(room_id: str) -> AgentExecutor:
    """Create appointment booking agent with LangChain and OpenAI function calling.
    
    Args:
        room_id: Unique room identifier
    
    Returns:
        Configured AgentExecutor instance
    """

    
    llm = _get_llm()
    
    current_date = _get_current_date()
    
    system_prompt = f"""You are a helpful medical appointment booking assistant. Today is {current_date}.

Your role:
- Help users search for healthcare providers they want to see
- Use provider IDs returned in search_providers output (primary_provider_id / matches[*].id)
- Clarify the appointment date they prefer (if not mentioned, ask for it)
- Retrieve and display available appointment slots (numbered 1, 2, 3, etc.)
- When a user selects a numbered slot (e.g., "slot 1" or "option 2"), ALWAYS use the select_slot tool with that number
- Suggest alternative dates if their preferred date has no availability
- Be conversational, warm, and helpful
- Keep technical fields internal (IDs, raw JSON, tool outputs)

CRITICAL WORKFLOW - FOLLOW EXACTLY:
1. User mentions a provider name → Call search_providers(provider_name)
2. EXTRACT the primary_provider_id from search_providers JSON response (e.g., if response has "primary_provider_id": 3, save ID=3)
3. Mention only the found provider name to user (never mention IDs)
4. Ask user for their preferred appointment date (if not already mentioned)
5. Call get_available_slots(provider_id=<THE ID FROM STEP 2>, date=<USER'S DATE>) - USE THE EXACT ID RETURNED BY search_providers
6. Display slots as numbered list (1, 2, 3, etc.)
7. When user selects a slot number → Call select_slot(slot_number) with that number
8. After select_slot succeeds, confirm the booking with provider name, date, and time

MANDATORY ID TRACKING:
- ALWAYS capture provider_id from search_providers response
- ALWAYS use that EXACT ID in get_available_slots - NEVER guess or use different IDs
- If you get these IDs: primary_provider_id=3, then call get_available_slots with provider_id=3
- Keep IDs strictly internal for tool calls; do not expose IDs in user-facing responses

RESPONSE SAFETY RULES:
- NEVER include provider IDs, slot context IDs, or internal keys in user-facing text
- NEVER paste raw JSON/tool output to the user
- Summarize tool results in natural language only

IMPORTANT: Slots are pre-verified as available. DO NOT re-check availability.

MISSING CONTEXT RULE:
- If provider or slot context is missing/not found, do not guess.
- Ask the user for BOTH: provider name and preferred appointment date.
- Then continue from step 1.

Use the available tools: search_providers, get_available_slots, select_slot.
Always confirm provider and date details before finalizing.
If errors occur, ask the user to clarify or try again."""
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad")
    ])
    
    def search_providers_wrapper(provider_name: str) -> str:
        """Search for matching healthcare providers. Returns JSON with provider IDs."""
        matches = get_matching_providers_llm(provider_name)
        
        # Store primary provider in context if found
        if matches:
            _set_room_context(room_id, {
                "primary_provider_id": matches[0]['id'],
                "provider_name": matches[0]['name']
            })
        
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
        result = get_available_slots(provider_id, room_id, date)
        
        try:
            result_data = json.loads(result)
        except:
            return result
        return json.dumps({
            "provider_id": provider_id,
            "requested_date": date,
            "slots": result_data.get("slots", []),
            "total_slots": result_data.get("count", 0),
            "all_available_dates": _get_all_provider_dates(provider_id) if date and result_data.get("count", 0) == 0 else None
        })
    
    def select_slot_wrapper(slot_number: int) -> str:
        """Resolve a slot number to actual appointment details.
        
        When user selects "slot 1" or "option 2", this maps the number to 
        the actual provider_id, date, and time from MongoDB storage.
        """
        slot_context = _get_slot_context(room_id)
        slots_list = slot_context.get("slots", [])
        provider_id = slot_context.get("provider_id")
        
        if not slots_list or slot_number < 1 or slot_number > len(slots_list):
            return json.dumps({
                "error": "invalid_slot_number",
                "message": "Slot context not found. Please search for a provider and request available slots again."
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
            name="select_slot",
            description="When user selects a numbered slot (e.g., 'slot 1', 'option 2'), use this tool to resolve the slot number to actual appointment details (provider_id, date, time). Slots are pre-verified as available.",
            func=select_slot_wrapper,
            args_schema=SelectSlotInput
        ),
    ]
    
    agent = create_openai_functions_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True)


# =============================================================================
# Helper Functions
# =============================================================================

def _get_all_provider_dates(provider_id: int) -> list:
    """Get all unique dates with available slots for a provider."""
    try:
        cursor = db.cursor()
        query = """
            SELECT DISTINCT DATE(ss.available_date) AS available_date
            FROM service_slots ss
            WHERE ss.provider_id = %s
            ORDER BY DATE(ss.available_date)
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


def handle_user_input(room_id: str, user_input: str, chat_history: list):
    """Handle user input with the appointment booking agent.
    
    Args:
        room_id: Unique room identifier
        user_input: Current user message
        chat_history: REQUIRED list of message dicts from client:
            [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
            Client must provide conversation history for context.
    
    Returns:
        Bot response string
    """
    langchain_history = _convert_client_history_to_langchain(chat_history)
    
    # Create agent executor
    agent_executor = create_langchain_agent(room_id)
    

    try:
        result = agent_executor.invoke({
            "input": user_input,
            "chat_history": langchain_history
        })
        bot_response = result.get("output", "")
    except Exception as e:
        logger.error(f"Agent error: {e}", exc_info=True)
        bot_response = ""

    return bot_response
