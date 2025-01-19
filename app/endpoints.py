from flask import Blueprint, render_template, flash

from app.models.chat_repo import ChatRepo
from app.resources.core.auth import verify_auth_token

# Initialize the Blueprint
endpoints = Blueprint('endpoints', __name__)

# Define the root route
@endpoints.route('/', methods=['GET'])
@verify_auth_token
def home():
    return render_template('chat.html')

@endpoints.route('/chat', methods=['GET'])
def chat():
    return render_template('chat.html')