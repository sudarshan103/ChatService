import os
import mysql.connector


db = mysql.connector.connect(
    host="localhost",
    user=os.getenv('MYSQL_USERNAME'),
    password=os.getenv('MYSQL_PASSWORD'),
    database="appointments"
)



def trim_messages(messages, max_length=15, preserve_count=1):
    if len(messages) <= max_length:
        return messages  # No trimming needed

    # Preserve the first 'preserve_count' messages
    preserved_messages = messages[:preserve_count]

    # Trim older messages from the remaining ones
    remaining_messages = messages[preserve_count:]
    trimmed_remaining = remaining_messages[-(max_length - preserve_count):]

    return preserved_messages + trimmed_remaining


def print_conversation(conversation):
    """
    Prints messages in a formatted conversation style.

    :param messages: List of message dictionaries
    """
    role_labels = {
        "system": "System:",
        "assistant": "Assistant:",
        "user": "User:"
    }

    for msg in conversation:
        role = role_labels.get(msg["role"], msg["role"].capitalize() + ":")
        print(f"{role} {msg['content']}")