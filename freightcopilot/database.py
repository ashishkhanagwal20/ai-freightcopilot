from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector

from freightcopilot.config import get_database_url


@contextmanager
def connect_database() -> Iterator[psycopg.Connection]:
    with psycopg.connect(get_database_url()) as connection:
        register_vector(connection)
        yield connection


def get_db_connection() -> Iterator[psycopg.Connection]:
    with connect_database() as connection:
        yield connection
