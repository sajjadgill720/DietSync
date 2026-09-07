"""
services/queue_publisher.py
RabbitMQ publisher for DietSync's asynchronous interaction check pipeline.

Per PROJECT_SPEC.md:
- Publishes minimal payload {job_id, drug_a_id, drug_b_id} (plus optional ephemeral
  patient allergies/diet factors).
- Single durable queue: "interaction_checks".
- delivery_mode=2 (persistent) so jobs survive broker restart.
"""

import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Union

import pika

logger = logging.getLogger("queue_publisher")

QUEUE_NAME = "interaction_checks"
DEFAULT_RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")


def get_connection_parameters(url: Optional[str] = None) -> pika.ConnectionParameters:
    """Parses AMQP URL or returns connection parameters."""
    amqp_url = url or DEFAULT_RABBITMQ_URL
    return pika.URLParameters(amqp_url)


def publish_interaction_job(
    job_id: Union[str, uuid.UUID],
    drug_a_id: int,
    drug_b_id: int,
    patient_allergies: Optional[List[str]] = None,
    patient_diet_factors: Optional[List[str]] = None,
    rabbitmq_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Publishes an interaction check job payload to RabbitMQ.

    :param job_id: Unique UUID identifier of the interaction job
    :param drug_a_id: PostgreSQL primary key of Drug A
    :param drug_b_id: PostgreSQL primary key of Drug B
    :param patient_allergies: Ephemeral patient allergy factors (optional)
    :param patient_diet_factors: Ephemeral patient dietary factors (optional)
    :param rabbitmq_url: Optional AMQP connection string
    :return: The published payload dictionary
    """
    payload = {
        "job_id": str(job_id),
        "drug_a_id": int(drug_a_id),
        "drug_b_id": int(drug_b_id),
    }

    if patient_allergies:
        payload["patient_allergies"] = patient_allergies
    if patient_diet_factors:
        payload["patient_diet_factors"] = patient_diet_factors

    params = get_connection_parameters(rabbitmq_url)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    try:
        # Ensure queue is durable so queued messages survive broker restarts
        channel.queue_declare(queue=QUEUE_NAME, durable=True)

        message_body = json.dumps(payload)
        properties = pika.BasicProperties(
            delivery_mode=2,  # Persistent message
            content_type="application/json",
        )

        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=message_body.encode("utf-8"),
            properties=properties,
        )

        logger.info(
            f"[queue_publisher] Successfully published job {job_id} "
            f"(Drug A: {drug_a_id}, Drug B: {drug_b_id}) to '{QUEUE_NAME}'"
        )
        return payload

    finally:
        channel.close()
        connection.close()


# Module-level alias
publish_job = publish_interaction_job
