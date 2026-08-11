"""Shared Prisma Client Python instance (Feature 1: User Identity & Data
Foundation). One process-wide client, connected/disconnected via the FastAPI
lifespan in app/main.py — callers elsewhere just import `prisma` and use it,
never instantiate their own Prisma() client.
"""

from prisma import Prisma

prisma = Prisma()


async def connect() -> None:
    if not prisma.is_connected():
        await prisma.connect()


async def disconnect() -> None:
    if prisma.is_connected():
        await prisma.disconnect()
