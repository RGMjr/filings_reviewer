# db_smoke_test.py
# Simple connectivity check to your Docker Postgres

import os

from dotenv import load_dotenv
import psycopg


def main() -> None:
    # Load DATABASE_URL from .env
    load_dotenv()
    url = os.getenv("DATABASE_URL")

    if not url:
        raise RuntimeError("DATABASE_URL is not set in .env")

    print(f"Connecting to: {url}")

    # Connect using psycopg (v3)
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            # 1) Show server version
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            print(f"Postgres version: {version}")

            # 2) List databases
            cur.execute("SELECT datname FROM pg_database ORDER BY datname;")
            dbs = [row[0] for row in cur.fetchall()]
            print("Databases:", dbs)


if __name__ == "__main__":
    main()
