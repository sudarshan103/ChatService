# import eventlet
# eventlet.monkey_patch()
import pika
import json
import logging
from functools import wraps

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Connection cache to avoid creating new connections for each message
_connection_cache = None
_channel_cache = None


def with_rabbitmq_connection(func):
    """Decorator to handle RabbitMQ connections safely"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        global _connection_cache, _channel_cache

        try:
            # Use existing connection if available
            if _connection_cache is None or not _connection_cache.is_open:
                # Create new connection
                params = pika.ConnectionParameters(
                    host='localhost',
                    heartbeat=600,
                    blocked_connection_timeout=300,
                    connection_attempts=3,
                    retry_delay=5
                )
                _connection_cache = pika.BlockingConnection(params)
                _channel_cache = _connection_cache.channel()
                logger.info("Created new RabbitMQ connection")

            # Execute the function with the channel
            return func(_channel_cache, *args, **kwargs)

        except pika.exceptions.AMQPConnectionError as e:
            # Connection error, clear cache
            logger.error(f"RabbitMQ connection error: {e}")
            _connection_cache = None
            _channel_cache = None
            raise

        except Exception as e:
            logger.error(f"RabbitMQ operation error: {e}")
            raise

    return wrapper


@with_rabbitmq_connection
def enqueue_message(channel, message, queue_name='default'):
    """
    Enqueue a message to RabbitMQ

    Args:
        channel: RabbitMQ channel (provided by decorator)
        message: Message to publish (string or dict)
        queue_name: Target queue name
    """
    try:
        # Convert dict to string if needed
        if isinstance(message, dict):
            message = json.dumps(message)

        # Ensure queue exists
        channel.queue_declare(queue=queue_name, durable=True)

        # Publish with delivery confirmation
        properties = pika.BasicProperties(
            delivery_mode=2,  # Make message persistent
            content_type='application/json'
        )

        channel.basic_publish(
            exchange='',
            routing_key=queue_name,
            body=message,
            properties=properties
        )

        logger.info(f"Message enqueued to {queue_name}")
        return True

    except Exception as e:
        logger.error(f"Failed to enqueue message: {e}")
        return False
