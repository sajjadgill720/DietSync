import asyncio
import os
import re
from typing import AsyncGenerator, Generator, Optional

import psycopg2
import psycopg2.extensions


def _sanitize_channel(channel: str) -> str:
    """Validate and quote channel name to avoid SQL injection."""
    # Allow alphanumeric and underscore identifiers
    if not re.match(r"^[A-Za-z0-9_]+$", channel):
        raise ValueError(f"Invalid PostgreSQL channel name: {channel!r}")
    return f'"{channel}"'


def get_connection(dsn: Optional[str] = None) -> psycopg2.extensions.connection:
    """
    Establish a psycopg2 connection set to autocommit mode (required for LISTEN/NOTIFY).
    Defaults to DATABASE_URL environment variable or standard local dev Postgres.
    """
    db_url = dsn or os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/dietsync"
    )
    # Normalize SQLAlchemy driver prefix if present (e.g. postgresql+psycopg2:// -> postgresql://)
    if db_url.startswith("postgresql+"):
        db_url = "postgresql://" + db_url.split("://", 1)[1]

    conn = psycopg2.connect(db_url)
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


async def listen_channel(
    channel: str,
    dsn: Optional[str] = None,
    timeout: Optional[float] = None,
    poll_interval: float = 0.05,
) -> AsyncGenerator[psycopg2.extensions.Notify, None]:
    """
    Asynchronously subscribe to a PostgreSQL channel and yield received notifications.

    Designed for use within FastAPI async endpoints and WebSocket handlers:
    - Runs blocking poll checks in a worker thread so the asyncio event loop remains responsive.
    - Yields psycopg2.extensions.Notify objects containing `.channel` and `.payload`.
    - Automatically executes UNLISTEN and closes the connection on exit or cancellation.

    :param channel: PostgreSQL notification channel name
    :param dsn: Optional connection string / DSN
    :param timeout: Maximum seconds to wait before stopping generator (None for infinite)
    :param poll_interval: Sleep interval (in seconds) between polls when no notifications are buffered
    """
    channel_quoted = _sanitize_channel(channel)
    conn = await asyncio.to_thread(get_connection, dsn)
    cursor = conn.cursor()

    try:
        cursor.execute(f"LISTEN {channel_quoted};")
        loop = asyncio.get_running_loop()
        start_time = loop.time()

        while True:
            # Non-blocking poll executed in thread pool
            await asyncio.to_thread(conn.poll)

            while conn.notifies:
                notify = conn.notifies.pop(0)
                yield notify

            if timeout is not None and (loop.time() - start_time) >= timeout:
                break

            await asyncio.sleep(poll_interval)
    finally:
        try:
            cursor.execute(f"UNLISTEN {channel_quoted};")
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def notify_channel(channel: str, payload: str = "", dsn: Optional[str] = None) -> None:
    """
    Send a NOTIFY to the specified PostgreSQL channel with an optional string payload.
    Used by workers and background tasks to push status updates.
    """
    channel_quoted = _sanitize_channel(channel)
    conn = get_connection(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(f"NOTIFY {channel_quoted}, %s;", (payload,))
    finally:
        conn.close()


def listen_channel_sync(
    channel: str,
    dsn: Optional[str] = None,
    timeout: Optional[float] = None,
) -> Generator[psycopg2.extensions.Notify, None, None]:
    """
    Synchronous generator for listening to a PostgreSQL channel.
    Useful for scripts, testing, or synchronous workers.
    """
    import select

    channel_quoted = _sanitize_channel(channel)
    conn = get_connection(dsn)
    cursor = conn.cursor()

    try:
        cursor.execute(f"LISTEN {channel_quoted};")
        while True:
            if select.select([conn], [], [], timeout) == ([], [], []):
                # Timeout reached
                break
            conn.poll()
            while conn.notifies:
                yield conn.notifies.pop(0)
    finally:
        try:
            cursor.execute(f"UNLISTEN {channel_quoted};")
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
