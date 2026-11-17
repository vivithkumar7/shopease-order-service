from sqlalchemy import inspect, text

from app.database.connection import engine


def main() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1")).scalar_one()
        tables = set(inspect(connection).get_table_names())

    expected_tables = {"orders", "order_items", "inventory_operations"}
    missing_tables = expected_tables - tables
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise RuntimeError(
            f"Connected to the database, but these tables are missing: {missing}. "
            "Run `alembic upgrade head`."
        )

    print("Database connection and order/inventory-operation tables verified.")


if __name__ == "__main__":
    main()
