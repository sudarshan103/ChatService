import json
from threading import Thread

import pika

from app.constants import chat_message_queue
from app.models.chat_repo import ChatRepo


def start_consumer():
    def callback(ch, method, properties, body):
        print(f"[x] Received: {body.decode()}")
        from app.run import app
        with app.app_context():
            ChatRepo.receive_create_message_command(json.loads(body.decode()))

    consume_messages(callback, chat_message_queue)

def init_broker_message_listener():
    consumer_thread = Thread(target=start_consumer, daemon=True)
    consumer_thread.start()

def consume_messages(callback, queue_name='default'):
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()

    # Declare the queue
    channel.queue_declare(queue=queue_name)

    # Define the callback function for message consumption
    channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)

    print(f"[*] Waiting for MQTT messages in '{queue_name}'. To exit press CTRL+C")
    channel.start_consuming()
