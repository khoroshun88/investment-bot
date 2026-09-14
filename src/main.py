import os
import psycopg


def main():
    db_name = os.environ["POSTGRES_DB"]
    db_user = os.environ["POSTGRES_USER"]
    db_password = os.environ["POSTGRES_PASSWORD"]

    print("Connecting to PostgreSQL...")

    with psycopg.connect(
        host="postgres",
        port=5432,
        dbname=db_name,
        user=db_user,
        password=db_password,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
            result = cur.fetchone()

    print(f"PostgreSQL response: {result}")
    print("Database connection test successful.")


if __name__ == "__main__":
    main()

