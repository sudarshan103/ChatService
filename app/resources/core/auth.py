from functools import wraps

from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, create_access_token, get_jwt


def generate_token(user_id, additional_data):
    return create_access_token(identity=str(user_id), additional_claims=additional_data)

def verify_auth_token(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            verify_jwt_in_request()
            user_data = get_jwt()
            return func(*args, **kwargs, user_data=user_data)
        except Exception as e:
            return jsonify({"message": "Unauthorized", "error": str(e)}), 401
    return wrapper