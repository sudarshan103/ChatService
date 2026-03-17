import os
from openai import OpenAI

from config import Config


# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def get_direct_completion(prompt, model=Config.LLM_MODEL, temperature=0):
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

def get_completion_from_messages(messages, model=Config.LLM_MODEL, temperature=0):
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
    

def get_completion_with_function_calling(messages, functions, model=Config.LLM_MODEL, temperature=0):
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


def llm_extract_single_line(prompt: str) -> str | None:
    """Invoke the configured LLM and return the first meaningful response line.

    Returns None on LLM failure, empty response, or when the model responds with NONE.
    """
    from langchain_openai import ChatOpenAI
    try:
        llm = ChatOpenAI(model=Config.LLM_MODEL, temperature=0)
        content = (llm.invoke(prompt).content or "").strip()
    except Exception:
        return None

    if not content:
        return None

    candidate = content.splitlines()[0].strip().strip('"').strip("'")
    if not candidate or candidate.upper() == "NONE":
        return None

    return candidate