import os

class Config:
    ENV = os.environ.get('ENV')
    SECRET_KEY = os.environ.get('SECRET_KEY')