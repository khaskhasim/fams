import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    """
    Get PostgreSQL connection (dict-style row)
    """
    conn = psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        connect_timeout=5
    )

    # autocommit mirip sqlite isolation_level=None
    conn.autocommit = True
    return conn
