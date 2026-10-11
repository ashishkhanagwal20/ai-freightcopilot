One pain point in freight is brokers dumping 500k-row CSV manifests that would choke a normal upload endpoint. I built an async bulk ingestion pipeline: the client uploads straight to S3 using a pre-signed URL, so no file bytes ever hit my web server. That upload fires an event into Redis, a Celery worker picks it up, streams the file from S3 in 5,000-row chunks using Polars — so memory stays flat under 100MB no matter the file size — validates each row with Pydantic, quarantines the bad rows to a separate error CSV, and bulk-loads the good ones into Postgres using COPY, which does upserts via ON CONFLICT DO UPDATE. Took ingestion of a 500k-row file from 20 minutes down to 35 seconds.

Layer	Tech
Upload	AWS S3 pre-signed URLs
Queue/broker	Redis (event queue) + Celery (worker)
Streaming parse	Polars (say Polars primarily — faster, lower memory than pandas; mention pandas chunksize as the fallback you know too)
Validation	Pydantic
DB write	PostgreSQL COPY via psycopg2.copy_expert
Error handling	Quarantine CSV back to S3