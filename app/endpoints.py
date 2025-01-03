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

@endpoints.route('/create-sample-chat', methods=['GET'])
def sample_message():
    room_mates = []
    room_mates.append(dict(name="Emp1",uuid="2d30094b-7a56-421b-b51c-08fbf9bf818a"))
    room_mates.append(dict(name="Emp2",uuid="c32f85f8-836c-4813-8bf1-272e7ce1bc2d"))
    room_id = ChatRepo.create_room(room_mates)
    ChatRepo.create_message(room_id,room_mates[0]["uuid"],room_mates[0]["name"],"Hello Emp2")
    return render_template('output.html')


@endpoints.route('/chat', methods=['GET'])
def chat():
    return render_template('chat.html')