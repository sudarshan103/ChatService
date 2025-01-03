import eventlet
import pika

def send_to_broker(message, queue_name='default'):
    eventlet.sleep(5)
    connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = connection.channel()

    # Declare the queue
    channel.queue_declare(queue=queue_name)

    # Publish the message
    channel.basic_publish(exchange='', routing_key=queue_name, body=message)
    connection.close()