import asyncio
from app.database import AsyncSessionLocal
from app.models.sofascore import PlayerHistory
from sqlalchemy.future import select

async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(PlayerHistory))
        players = res.scalars().all()
        print(f"Total players in DB: {len(players)}")

if __name__ == "__main__":
    asyncio.run(main())
