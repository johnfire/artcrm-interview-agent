import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()


@contextmanager
def db():
    conn = psycopg2.connect(
        os.environ["DATABASE_URL"],
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
