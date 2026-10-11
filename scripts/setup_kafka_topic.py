from confluent_kafka.admin import AdminClient, NewTopic

from freightcopilot.config import (
    KAFKA_BOOKING_TOPIC,
    KAFKA_BOOTSTRAP_SERVERS,
)


def main() -> None:
    admin = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})
    if KAFKA_BOOKING_TOPIC in admin.list_topics(timeout=10).topics:
        print(f"Kafka topic already exists: {KAFKA_BOOKING_TOPIC}")
        return

    futures = admin.create_topics(
        [NewTopic(KAFKA_BOOKING_TOPIC, num_partitions=1, replication_factor=1)]
    )

    for topic, future in futures.items():
        future.result()
        print(f"Created Kafka topic: {topic}")


if __name__ == "__main__":
    main()
