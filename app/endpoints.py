from flask import Blueprint, render_template, flash

from app.models.chat_repo import ChatRepo

# Initialize the Blueprint
endpoints = Blueprint('endpoints', __name__)

# Define the root route
@endpoints.route('/', methods=['GET'])
def home():
    flash('Welcome to Flask with Python!')
    return render_template('index.html')

@endpoints.route('/create-chat', methods=['GET'])
def sample_message():
    room_mates = []
    room_mates.append(dict(name="Emp1",uuid="2d30094b-7a56-421b-b51c-08fbf9bf818a"))
    room_mates.append(dict(name="Emp2",uuid="c32f85f8-836c-4813-8bf1-272e7ce1bc2d"))
    room_id = ChatRepo.create_room(room_mates)
    ChatRepo.create_message(room_id,room_mates[0]["uuid"],room_mates[0]["name"],"Hello Emp2")
    return render_template('output.html')

@endpoints.route('/create-socket-chat', methods=['GET'])
def sample_socket_message():
    return render_template('output.html')