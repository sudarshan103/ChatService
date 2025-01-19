import json
from threading import Thread

import pika

from app.constants import chat_message_queue, chat_delivery_update_queue
from app.models.chat_repo import ChatRepo


def start_message_consumer():
    def callback(ch, method, properties, body):
        print(f"[chat] Received: {body.decode()}")
        from app.run import app
        with app.app_context():
            ChatRepo.receive_create_message_command(json.loads(body.decode()))

    consume_messages(callback, chat_message_queue)

def start_delivery_updates_consumer():
    def callback(ch, method, properties, body):
        print(f"[deliveryUpdate] Received: {body.decode()}")
        from app.run import app
        with app.app_context():
            ChatRepo.update_delivery_status(json.loads(body.decode()))

    consume_messages(callback, chat_delivery_update_queue)


def init_broker_message_listener():
    Thread(target=start_message_consumer, daemon=True).start()
    Thread(target=start_delivery_updates_consumer, daemon=True).start()

def consume_messages(callback, queue_name='default'):
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()

    # Declare the queue
    channel.queue_declare(queue=queue_name)

    # Define the callback function for message consumption
    channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)

    print(f"[*] Waiting for MQTT messages in '{queue_name}'. To exit press CTRL+C")
    channel.start_consuming()