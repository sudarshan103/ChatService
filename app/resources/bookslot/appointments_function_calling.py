from langchain.agents import Tool, AgentExecutor, create_openai_functions_agent
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import HumanMessage, AIMessage
from datetime import datetime, timezone
import json
import os

from app.models.extensions import db

prompt = f"""
You are an assistant, helping a user to book an appointment with a service provider at date and time as per the provider's availability.
While displaying provider, consider him as a Doctor in this use case & do not display him as a 'provider'.
Follow these rules:
- Make sure the user provides the provider name and future date both as a basic input to process further.
- When the provider name is provided by user, query the system by calling the relevant function, check the provider name matches the most to any of the outcome item, if matches consider that as a valid input & use provider id field for further usage, else ask user for provider name again.
- When the provider id is determined, show user with his name & service details before asking further inputs.
- When the provider id is determined and date and time inputs are also provided, call relevant function.
- If the provider id is determined and user provided a date without time, show all the available time slots as options for that date and provider id using relevant function.
- Show time slots only when user has not provided the time value or provider is not available
- Whenever the time slots are listed, always list them as numbered options, ask user to choose one of the option's number.
- Whenever the time slot options are shown, process associated slot with user chosen number as an input for datetime, if user provides number from listed ones, confirm the booking.
- Whenever the user rejects a provided time slot (e.g., says "No" or declines in any way), do not consider the date input, ask for new date and show all the available time slots as options for new date and provider id using relevant function.
- If the user asks for alternative slots, immediately get the available slot by provider id, without date filter, fetch all available slots, and display them in a numbered format.
- If the user provides a new date or time, process that input instead of fetching all slots.
- If provider is available, confirm appointment before finalizing.
- If the user provides a specific date and there are no available slots for that provider on that date, explicitly inform the user that the Doctor is not available on the requested date.Do NOT display slots from other dates.Ask the user whether they would like to see the nearest available dates.Only fetch and display slots without date filter if the user confirms they want alternative dates, otherwise exit the conversation by saying ok.
- While showing the time slots, show the dates in format '13 Jan 2025, 01:00pm' with the time in 12 hour format, skip the seconds part.
- While showing the time slots, skip dates part when the date input was provided and corresponding slots were available.
- If the user selects a time from the available options, proceed with booking instead of checking availability again.
"""


def get_matching_provider_names(provider_name):
    cursor = db.cursor(dictionary=True)
    
    query = """
        SELECT sp.id, sp.name, sp.service
        FROM service_providers sp
        WHERE sp.name LIKE %s
    """
    
    params = [f"%{provider_name}%"]
    
    cursor.execute(query, tuple(params))
    provider_names = cursor.fetchall()
    cursor.close()
    
    return provider_names


def get_available_slots(provider_id, date=None):
    cursor = db.cursor(dictionary=True)

    query = """
        SELECT ss.available_date, ss.available_time 
        FROM service_slots ss
        JOIN service_providers sp ON ss.provider_id = sp.id
        WHERE sp.id = %s
    """
    
    params = [provider_id]

    if date:
        query += " AND ss.available_date = %s"
        params.append(date)

    cursor.execute(query, tuple(params))
    
    # Print the actual executed query
    # print("Executing Query:", cursor.statement)

    slots = cursor.fetchall()
    cursor.close()

    return slots



def check_availability(provider_id, date, time):
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


functions=[
             {
                "name": "get_matching_provider_names",
                "description": "Fetch available doctor names to match the one being queried by user",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provider_name": {"type": "string", "description": "Doctor's name"}
                    },
                    "required": ["provider_name"] 
                },
                "response": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "description": "Available provider with its id, name & service offering"
                    },
                    "description": "A list of matching provider names from system. Returns an empty list if no names are matching."
                }
            },
            {
                "name": "get_available_slots",
                "description": "Fetch available time slots for a doctor",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provider_id": {"type": "integer", "description": "Doctor's id"},
                        "date": {"type": "string", "format": "date", "description": "Appointment date (YYYY-MM-DD) optional"}
                    },
                    "required": ["provider_id"] 
                },
                "response": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "description": "Available time slot in YYYY-MM-DD HH:MM:SS format (24-hour format)."
                    },
                    "description": "A list of available time slots for the provider. Returns an empty list if no slots are available."
                }
            },
            {
                "name": "check_availability",
                "description": "Check if a service provider (doctor) is available at a specific date and time.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "provider_id": {
                            "type": "integer",
                            "description": "The id of the doctor or service provider."
                        },
                        "date": {
                            "type": "string",
                            "format": "date",
                            "description": "The appointment date in YYYY-MM-DD format."
                        },
                        "time": {
                            "type": "string",
                            "description": "The appointment time in HH:MM:SS format (24-hour format)."
                        } 
                    },
                    "required": ["provider_id", "date", "time"]
                },
                "response": {
                    "type": "boolean",
                    "description": "Returns true if the provider is available, otherwise false."
                }
            }

        ]

# Initialize LangChain components (one-time setup)
def _initialize_agent():
    """Initialize LangChain agent and related components."""
    tools = [
        Tool(
            name="get_matching_provider_names",
            func=get_matching_provider_names,
            description="Fetch available doctor names to match the one being queried by user. Takes doctor's name as input."
        ),
        Tool(
            name="get_available_slots",
            func=lambda provider_id, date=None: get_available_slots(int(provider_id), date),
            description="Fetch available time slots for a doctor. Takes provider_id (integer) and optional date (YYYY-MM-DD) as inputs."
        ),
        Tool(
            name="check_availability",
            func=lambda provider_id, date, time: check_availability(int(provider_id), date, time),
            description="Check if a doctor is available at a specific date and time. Takes provider_id (integer), date (YYYY-MM-DD), and time (HH:MM:SS) as inputs."
        ),
    ]

    llm = ChatOpenAI(
        model="gpt-3.5-turbo",
        temperature=0
    )

    prompt_template = ChatPromptTemplate.from_messages([
        ("system", prompt),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])

    agent = create_openai_functions_agent(llm, tools, prompt_template)
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        max_iterations=10
    )

    return agent_executor, tools

_agent_executor = None
_tools = None


def _get_agent_executor():
    global _agent_executor, _tools
    if _agent_executor is None:
        _agent_executor, _tools = _initialize_agent()
    return _agent_executor

def _get_chat_history_from_repo(room_id):
    """Fetch chat history using existing ChatRepo's get_recent_messages."""
    from app.models.chat_repo import ChatRepo
    
    messages = ChatRepo.get_recent_messages(room_id)
    
    # Convert to LangChain message format
    chat_history = []
    for msg in messages:
        content = msg.get('message', '')
        # Convert all messages to HumanMessage for now
        # Adjust this logic based on how you identify bot vs user messages
        chat_history.append(HumanMessage(content=content))
    
    return chat_history

def handle_user_input(room_id, user_input):
    """Handle user input using LangChain agent with ChatRepo conversation history."""
    agent_executor = _get_agent_executor()

    # Get chat history from ChatRepo
    chat_history = _get_chat_history_from_repo(room_id)
    
    # Run agent with current conversation history
    result = agent_executor.invoke({
        "input": user_input,
        "chat_history": chat_history
    })

    bot_response_content = result.get("output", "")

    return bot_response_content



   
