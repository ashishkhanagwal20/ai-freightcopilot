from langgraph.checkpoint.postgres import PostgresSaver

from freightcopilot.config import get_database_url


def main() -> None:
    with PostgresSaver.from_conn_string(get_database_url()) as checkpointer:
        checkpointer.setup()

    print("LangGraph Postgres checkpoint tables are ready.")


if __name__ == "__main__":
    main()