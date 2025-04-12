import eventlet
eventlet.monkey_patch()

import json
import pika
import threading
import time
import logging

from app.constants import chat_message_queue, chat_delivery_update_queue, REDIS_KEY
from app.models.chat_repo import ChatRepo

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RabbitMQConsumer:
    """Thread-safe RabbitMQ consumer that integrates with SocketIO"""

    def __init__(self, socketio, app, queue_name, message_handler):
        self.socketio = socketio
        self.app = app
        self.queue_name = queue_name
        self.message_handler = message_handler
        self.connection = None
        self.channel = None
        self.is_consuming = False
        self.reconnect_delay = 5  # seconds

    def connect(self):
        """Establish connection to RabbitMQ"""
        try:
            # Connection parameters with retry and heartbeat
            params = pika.ConnectionParameters(
                host='localhost',
                heartbeat=600,  # 10-minute heartbeat
                blocked_connection_timeout=300,
                connection_attempts=3,
                retry_delay=5
            )

            self.connection = pika.BlockingConnection(params)
            self.channel = self.connection.channel()

            # Declare queue with durability for message persistence
            self.channel.queue_declare(queue=self.queue_name, durable=True)

            # Set prefetch to prevent overloading this consumer
            self.channel.basic_qos(prefetch_count=1)

            logger.info(f"Connected to RabbitMQ, queue: {self.queue_name}")
            return True

        except Exception as e:
            logger.error(f"RabbitMQ connection error: {e}")
            return False

    def process_message(self, body):
        """Process received message using the provided handler"""
        try:
            # Parse message
            message_data = json.loads(body.decode('utf-8'))

            with self.app.app_context():
                result = self.message_handler(message_data)

                if self.queue_name == chat_message_queue and result:
                    result["action"] = 'message_received'
                    logger.info(f"##Chat Message processed : {message_data}")

            return True

        except Exception as e:
            logger.error(f"Message processing error: {e}")
            return False


    def message_callback(self, ch, method, properties, body):
        """Callback for received messages"""
        try:
            logger.info(f"Received message from queue: {self.queue_name}")

            # Process message in the app's thread pool using socketio
            success = self.socketio.start_background_task(
                self.process_message, body
            )

            # Acknowledge message after sending to background task
            ch.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as e:
            logger.error(f"Error in message callback: {e}")
            # Negative acknowledge with requeue on error
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

    def start_consuming(self):
        """Start consuming messages"""
        try:
            if not self.connect():
                logger.error(f"Failed to connect to RabbitMQ for queue: {self.queue_name}")
                return

            # Register consumer
            self.channel.basic_consume(
                queue=self.queue_name,
                on_message_callback=self.message_callback
            )

            self.is_consuming = True
            logger.info(f"Started consuming messages from {self.queue_name}")

            # Start consuming - blocking call
            self.channel.start_consuming()

        except Exception as e:
            logger.error(f"Error while consuming from {self.queue_name}: {e}")
            self.is_consuming = False

            # Attempt to reconnect after delay
            time.sleep(self.reconnect_delay)
            self.start_consuming()

    def stop_consuming(self):
        """Stop consuming messages"""
        try:
            if self.channel and self.is_consuming:
                self.channel.stop_consuming()
                self.is_consuming = False

            if self.connection and self.connection.is_open:
                self.connection.close()

            logger.info(f"Stopped consuming messages from {self.queue_name}")

        except Exception as e:
            logger.error(f"Error stopping consumer for {self.queue_name}: {e}")


def init_broker_message_listener(socketio, app):
    """Initialize message consumers for chat messages and delivery updates"""
    # Create consumer instances
    consumer_configs = [
        {
            'queue_name': chat_message_queue,
            'handler': lambda data: ChatRepo.process_new_message(data)
        },
        {
            'queue_name': chat_delivery_update_queue,
            'handler': lambda data: ChatRepo.update_delivery_status(data)
        }
    ]

    consumers = []

    # Start each consumer in its own thread
    for config in consumer_configs:
        consumer = RabbitMQConsumer(
            socketio=socketio,
            app=app,
            queue_name=config['queue_name'],
            message_handler=config['handler']
        )

        consumer_thread = threading.Thread(
            target=consumer.start_consuming,
            daemon=True
        )
        consumer_thread.start()

        consumers.append(consumer)

    # Store references to consumers for cleanup
    app.rabbitmq_consumers = consumers

    return consumers
