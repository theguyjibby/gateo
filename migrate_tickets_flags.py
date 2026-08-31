"""
Migration for the TicketsUsers flag rename/partitioning.

Renames the `is_purchased` column to `is_successful` and adds an
`is_free` boolean column, then backfills `is_free` for existing free
tickets (successful bookings with price 0 that are not admin-issued).

Runs against the app's configured database (DATABASE_URL in production).
For a fresh database whose tables do not exist yet, it first creates the
schema from the models (which already include the new columns), then
skips the column operations (no-op). Safe to run more than once.

Run:  python migrate_tickets_flags.py
"""

from sqlalchemy import inspect, text

import app as app_module

TABLE = 'tickets_users'


def run():
    db = app_module.db
    engine = db.engine  # requires app context
    dialect = engine.dialect.name

    def column_names(name):
        return [c['name'] for c in inspect(engine).get_columns(name)]

    # Fresh database: create schema so the tables exist, then the column
    # operations below become no-ops (new columns are already present).
    if TABLE not in inspect(engine).get_table_names():
        print(f"Table '{TABLE}' not found. Creating schema for a fresh database...")
        db.create_all()
        print("Schema created with new columns (is_successful, is_free). Nothing else to do.")
        return

    # 1. Rename is_purchased -> is_successful (identical SQL on sqlite/pg)
    cols = column_names(TABLE)
    if 'is_purchased' in cols and 'is_successful' not in cols:
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE tickets_users RENAME COLUMN is_purchased TO is_successful"
            ))
        print("Renamed is_purchased -> is_successful")
    elif 'is_successful' in cols:
        print("is_successful already present (rename skipped)")
    else:
        raise RuntimeError("Neither is_purchased nor is_successful column found")

    # 2. Add is_free column if missing
    cols = column_names(TABLE)
    if 'is_free' not in cols:
        with engine.begin() as conn:
            if dialect == 'sqlite':
                conn.execute(text(
                    "ALTER TABLE tickets_users ADD COLUMN is_free BOOLEAN DEFAULT 0"
                ))
            else:
                conn.execute(text(
                    "ALTER TABLE tickets_users ADD COLUMN is_free BOOLEAN DEFAULT FALSE"
                ))
        print("Added is_free column")
    else:
        print("is_free already present (add skipped)")

    # 3. Backfill is_free for existing free tickets
    with engine.begin() as conn:
        res = conn.execute(text(
            "UPDATE tickets_users SET is_free = 1 "
            "WHERE is_successful = 1 AND ticket_price = 0 AND is_admin_issued = 0"
        ))
        print(f"Backfilled is_free for {res.rowcount} free ticket(s)")

    print("Migration complete.")


if __name__ == '__main__':
    with app_module.app.app_context():
        run()
