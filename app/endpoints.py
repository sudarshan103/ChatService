from flask import Blueprint, render_template, flash

# Initialize the Blueprint
endpoints = Blueprint('endpoints', __name__)

# Define the root route
@endpoints.route('/', methods=['GET'])
def home():
    flash('Welcome to Flask with Python!')
    return render_template('output.html')