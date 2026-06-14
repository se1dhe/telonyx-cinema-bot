import asyncio
from sqlalchemy import text
from telonyx_cinema_bot.config import get_settings
from telonyx_cinema_bot.db import create_engine

async def migrate():
    settings = get_settings()
    engine = create_engine(settings.database_url)
    async with engine.begin() as conn:
        print("Dropping old news_posts table...")
        await conn.execute(text("DROP TABLE IF EXISTS news_posts CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS news_urls CASCADE;"))
        print("Recreating schema...")
        from telonyx_cinema_bot.models import Base
        await conn.run_sync(Base.metadata.create_all)
    print("Done!")

if __name__ == "__main__":
    asyncio.run(migrate())
