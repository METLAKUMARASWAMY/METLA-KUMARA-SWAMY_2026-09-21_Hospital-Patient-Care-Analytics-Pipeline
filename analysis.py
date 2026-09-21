"""
analysis.py
Runs the business queries in sql/analysis_queries.sql on the loaded database
and prints the results (answers to the hospital's three goals).
"""
import os
import pandas as pd
from config import BASE_DIR

SQL_FILE = os.path.join(BASE_DIR, "sql", "analysis_queries.sql")


def read_queries():
    """Split the .sql file into (title, query) pairs using the '-- name:' markers."""
    with open(SQL_FILE) as f:
        blocks = f.read().split("-- name:")[1:]
    queries = []
    for block in blocks:
        title, _, body = block.partition("\n")
        queries.append((title.strip(), body.strip().rstrip(";")))
    return queries


def run_analysis(engine):
    pd.set_option("display.width", 140)
    print("\n" + "=" * 70 + "\n BUSINESS INSIGHTS\n" + "=" * 70)
    for title, query in read_queries():
        print(f"\n>> {title}")
        print(pd.read_sql(query, engine).to_string(index=False))


if __name__ == "__main__":
    from load import get_engine
    run_analysis(get_engine())
