"""Package init.

On Windows, psycopg3's async driver refuses to run on the default
ProactorEventLoop, so we install the selector policy before any event loop
is created. This runs on the first `import app...` in every entry point
(uvicorn, alembic, scripts, tests).
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
