The riskiest part of the platform is the moment a carrier accepts a load — because two brokers could try to book the same load at once, or a booking could fail halfway through and leave the system in a broken state. I built this as a **Saga Orchestrator** that coordinates the booking across four services — Order, Carrier, Payment, and Notification — instead of using one giant database transaction, which isn't possible across microservices.

Before anything starts, I take a **distributed lock on the load using Redis** so only one broker can book it at a time. Then the orchestrator walks through the steps in order — mark the load pending, reserve the carrier's truck, place a payment hold. If any step fails — say the shipper's credit hold gets declined — I don't just error out. I run **compensating transactions** that undo everything that already succeeded, in reverse order, so the system always ends up consistent.

The other problem I solved was making sure that when we update the database *and* need to notify the driver, those two things never get out of sync — like if the container crashes right after the DB write but before the notification goes out. I used the **Transactional Outbox pattern**: the event gets written to an outbox table in the *same* database transaction as the booking, and a background CDC worker picks it up and delivers it reliably.

Orchestration logic	Python (FastAPI/Flask service) or Temporal.io / AWS Step Functions
Distributed lock	Redis (Redlock algorithm)
Messaging/outbox delivery	Debezium + Kafka (or AWS DMS + SQS/SNS if you want to lean AWS)
Databases (per service)	PostgreSQL (own DB per microservice — important detail, don't skip it)
Idempotency keys	Stored in Postgres or Redis, checked at each service boundary