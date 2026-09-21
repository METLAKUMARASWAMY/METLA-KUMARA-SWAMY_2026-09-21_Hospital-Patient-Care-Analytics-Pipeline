"""
load.py  -  L of ETL
Loads the clean tables into the MySQL database (hospital_db).
Also saves a CSV copy of every clean table in data/processed/ (backup / staging).
"""
import os
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from config import DB_CONFIG, USE_SQLITE, BASE_DIR, PROCESSED_DIR

logger = logging.getLogger(__name__)


def get_engine():
    if USE_SQLITE:                                   # optional: test without MySQL
        return create_engine(f"sqlite:///{os.path.join(BASE_DIR, 'hospital.db')}")

    server_url = URL.create(
        drivername="mysql+mysqlconnector",
        username=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
    )
    # create the database automatically if it does not exist yet
    with create_engine(server_url).connect() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}"))

    return create_engine(server_url.set(database=DB_CONFIG["database"]))


def save_processed(clean):
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    for name, df in clean.items():
        df.to_csv(os.path.join(PROCESSED_DIR, f"{name}.csv"), index=False)
    logger.info(f"Saved {len(clean)} clean tables as CSV in data/processed/")


def load(clean):
    save_processed(clean)
    engine = get_engine()
    for table_name, df in clean.items():
        df.to_sql(table_name, con=engine, if_exists="replace", index=False)
        logger.info(f"Loaded {len(df):>5} rows into '{table_name}' table")
    # a fresh schedule was loaded, so emergency bookings made on the old schedule are cleared
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS emergency_bookings"))
    return engine
