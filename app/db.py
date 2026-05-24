import os

import asyncpg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


async def create_pool() -> asyncpg.Pool:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing. Check your .env file.")

    return await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=10,
    )
