import json

from confluent_kafka import Consumer

from freightcopilot.config import (
    KAFKA_BOOKING_TOPIC,
    KAFKA_BOOTSTRAP_SERVERS,
)
from freightcopilot.database import connect_database


def record_event_once(event: dict) -> bool:
    """Record the mock downstream side effect once per event ID."""
    with connect_database() as connection:
        row = connection.execute(
            """
            INSERT INTO processed_booking_events (
                event_id,
                approval_id,
                booking_id,
                event_type
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            RETURNING event_id
            """,
            (
                event["event_id"],
                event["approval_id"],
                event["booking_id"],
                event["event_type"],
            ),
        ).fetchone()

    return row is not None


def main() -> None:
    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
            "group.id": "freightcopilot-booking-notifications-v1",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([KAFKA_BOOKING_TOPIC])
    print(f"Listening for booking events on {KAFKA_BOOKING_TOPIC}.")

    try:
        while True:
            message = consumer.poll(1.0)
            if message is None:
                continue
            if message.error():
                raise RuntimeError(f"Kafka consumer error: {message.error()}")

            event = json.loads(message.value().decode("utf-8"))
            inserted = record_event_once(event)

            if inserted:
                print(
                    "Recorded mock downstream notification for booking "
                    f"{event['booking_id']} (event {event['event_id']})."
                )
            else:
                print(
                    f"Ignored duplicate event {event['event_id']} using the "
                    "database idempotency key."
                )

            # Commit only after the database transaction succeeds. If the
            # process crashes between DB commit and this offset commit, Kafka
            # may redeliver; the event_id primary key makes that safe.
            consumer.commit(message=message, asynchronous=False)
    except KeyboardInterrupt:
        print("Stopping booking-event consumer.")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
