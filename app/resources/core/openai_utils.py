import os
from openai import OpenAI


# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def get_direct_completion(prompt, model="gpt-3.5-turbo", temperature=0):
    """
    Get a completion for a simple prompt using OpenAI API.
    """
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature  # Controls randomness
        )
        return response.choices[0].message.content

    except Exception as e:
        print(f"Error: {e}")
        return None

def get_completion_from_messages(messages, model="gpt-3.5-turbo", temperature=0):
    """
    Get a completion for a list of messages (useful for multi-turn chats).
    """
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature
        )
        return response.choices[0].message.content

    except Exception as e:
        print(f"Error: {e}")
        return None
    

def get_completion_with_function_calling(messages, functions, model="gpt-3.5-turbo", temperature=0):
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            functions=functions,
            temperature=temperature,
            function_call="auto"
        )
        return response.choices[0].message

    except Exception as e:
        print(f"Error: {e}")
        return None