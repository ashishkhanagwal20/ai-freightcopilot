from freightcopilot.database import connect_database


with connect_database() as connection:
    result = connection.execute(
        "SELECT extname FROM pg_extension WHERE extname = 'vector'"
    ).fetchone()
    if result:
        print(f"Connected to Postgres; pgvector extension is enabled: {result[0]}")
    else:
        print("Connected to Postgres, but the pgvector extension was not found.")
