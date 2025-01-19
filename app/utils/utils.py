
import re

from app.constants import sql_injection_pattern


def contains_sql_injection_chars(input_text: str) -> bool:
    return bool(re.search(sql_injection_pattern, input_text))

def is_integer(value):
    if isinstance(value, str) and value.isdigit():
        return True
    return isinstance(value, int)