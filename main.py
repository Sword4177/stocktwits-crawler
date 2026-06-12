import asyncio
import logging
from crawler import run_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("crawler.log", encoding="utf-8"),
    ],
)

if __name__ == "__main__":
    asyncio.run(run_loop())
