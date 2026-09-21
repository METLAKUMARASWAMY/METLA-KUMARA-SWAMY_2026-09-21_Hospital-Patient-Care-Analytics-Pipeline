"""
pipeline.py
Runs the complete Hospital Patient Care ETL pipeline:
    Extract -> Transform -> Validate -> Load -> Analyse
Usage:  python pipeline.py
"""
import os
import time
import logging
from config import LOG_DIR
from extract import extract
from transform import transform
from validation import validate
from load import load
from analysis import run_analysis

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(os.path.join(LOG_DIR, "pipeline.log")),
              logging.StreamHandler()],
)
logger = logging.getLogger("pipeline")


def run_pipeline():
    start = time.time()
    logger.info("===== Hospital ETL pipeline started =====")
    try:
        # Extract
        logger.info("STEP 1/4: EXTRACT")
        raw = extract()

        # Transform
        logger.info("STEP 2/4: TRANSFORM")
        clean = transform(raw)

        # Validate
        logger.info("STEP 3/4: VALIDATE")
        validate(clean)

        # Load
        logger.info("STEP 4/4: LOAD")
        engine = load(clean)

        logger.info(f"===== Pipeline finished successfully in {time.time() - start:.1f}s =====")
    except AssertionError as e:
        logger.error(f"Validation failed: {e}. Data NOT loaded.")
        raise
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        raise

    # Analyse (answers the business questions)
    run_analysis(engine)


if __name__ == "__main__":
    run_pipeline()
