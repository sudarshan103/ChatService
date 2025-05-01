from app.models.extensions import redis_client
from app.resources.bookslot.appointment_utils import db, trim_messages
from app.resources.core.openai_utils import get_completion_with_function_calling
import json

prompt = f"""
You are an assistant working in year 2025, helping a user to book an appointment with a service provider at date and time as per the provider's availability.
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
- If provider is not available, get the available slot by provider id, without date filter, show all the available time slots as per the function response.
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

def get_conversation(room_id):
    convo_json = redis_client.get(f"chat:{room_id}")
    if convo_json:
        return json.loads(convo_json)
    else:
        return [{'role': 'system', 'content': prompt}]

def save_conversation(room_id, conversation):
    redis_client.set(f"chat:{room_id}", json.dumps(conversation))

def handle_user_input(room_id, user_input):
    conversation = get_conversation(room_id)
    conversation.append({'role': 'user', 'content': user_input})

    while True:
        conversation = trim_messages(conversation)
        bot_response = get_completion_with_function_calling(conversation, functions)

        if bot_response.function_call:
            function_name = bot_response.function_call.name
            function_args = json.loads(bot_response.function_call.arguments)

            if function_name == "get_matching_provider_names":
                function_response = get_matching_provider_names(**function_args)
            elif function_name == "get_available_slots":
                function_response = get_available_slots(**function_args)
            elif function_name == "check_availability":
                function_response = check_availability(**function_args)
            else:
                function_response = {}

            conversation.append({
                'role': 'function',
                'name': function_name,
                'content': json.dumps(function_response, default=str)
            })

        else:
            conversation.append({'role': 'assistant', 'content': bot_response.content})
            break

    save_conversation(room_id, conversation)
    return bot_response.content



   
