Once loads are booked and drivers are on the road, brokers need to find available trucks near a pickup point — fast. I built this as a CQRS( Commad Query Responsibility Segregation )-based geospatial engine, splitting the write-heavy telemetry stream from the read-heavy search queries.

**Write path:** Driver apps ping GPS every 5 seconds. Instead of writing straight to a database (which would choke under 100K+ concurrent devices), pings go to Kafka first, partitioned by `driver_id` so each driver's location updates stay in order. Consumer workers then do two things: update a Redis geo-index for instant reads, and batch-write to PostGIS asynchronously for historical route auditing.

**Read path:** When a broker clicks "Find Nearby Carriers," the query hits Redis — not the database — using `GEOSEARCH` within a 25-mile radius. That comes back in under 15ms. Results are then filtered in-memory by live constraints like equipment type and hours-of-service remaining, and the broker sends an offer to the top match.

**Result:** search latency dropped from ~1.2s to ~15ms across 100,000 active vehicles.

Kafka backbone	Amazon MSK
Real-time geo index	Amazon ElastiCache for Redis
Durable/audit store	Amazon RDS/Aurora for PostgreSQL (PostGIS)
Consumer workers + API	Amazon ECS on Fargate