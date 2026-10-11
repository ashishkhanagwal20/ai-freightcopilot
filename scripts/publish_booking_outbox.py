import argparse
import json
import time

from confluent_kafka import Producer

from freightcopilot.config import KAFKA_BOOTSTRAP_SERVERS
from freightcopilot.database import connect_database


def load_pending_events() -> list[tuple]:
    with connect_database() as connection:
        return connection.execute(
            """
            SELECT event_id, aggregate_id, topic, payload
            FROM booking_outbox
            WHERE published_at IS NULL
            ORDER BY created_at
            LIMIT 50
            """
        ).fetchall()


def mark_published(event_id) -> None:
    with connect_database() as connection:
        connection.execute(
            """
            UPDATE booking_outbox
            SET published_at = now(), attempts = attempts + 1, last_error = NULL
            WHERE event_id = %s AND published_at IS NULL
            """,
            (event_id,),
        )


def mark_failed(event_id, error: str) -> None:
    with connect_database() as connection:
        connection.execute(
            """
            UPDATE booking_outbox
            SET attempts = attempts + 1, last_error = %s
            WHERE event_id = %s AND published_at IS NULL
            """,
            (error[:2000], event_id),
        )


def publish_event(producer: Producer, row: tuple) -> bool:
    event_id, aggregate_id, topic, payload = row
    delivery_result: dict[str, str | None] = {}

    def on_delivery(error, _message) -> None:
        delivery_result["error"] = str(error) if error else None

    try:
        producer.produce(
            topic=topic,
            key=str(aggregate_id),
            value=json.dumps(payload),
            callback=on_delivery,
        )
        outstanding = producer.flush(10)
        if outstanding:
            raise TimeoutError(
                f"Kafka delivery timed out with {outstanding} message(s) pending."
            )
        if delivery_result.get("error"):
            raise RuntimeError(delivery_result["error"])
    except Exception as exc:
        mark_failed(event_id, str(exc))
        print(f"Could not publish outbox event {event_id}: {exc}")
        return False

    mark_published(event_id)
    print(f"Published {payload['event_type']} event {event_id} to {topic}.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish approved-booking outbox events to Kafka."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Check the outbox once and exit instead of polling continuously.",
    )
    args = parser.parse_args()

    producer = Producer(
        {"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS}
    )

    try:
        while True:
            events = load_pending_events()
            if not events:
                print("No unpublished booking events.")
            else:
                for event in events:
                    publish_event(producer, event)

            if args.once:
                break
            time.sleep(2)
    except KeyboardInterrupt:
        print("Stopping outbox publisher.")
    finally:
        producer.flush(10)


if __name__ == "__main__":
    main()
