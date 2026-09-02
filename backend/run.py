"""Dev entrypoint: `python run.py` (add `--reload` for autoreload).

uvicorn hardcodes ProactorEventLoop on Windows, but psycopg3's async driver
only works on a selector loop. We override uvicorn's loop factory before
starting the server.
"""
import sys

import uvicorn

if sys.platform == "win32":
    import asyncio

    import uvicorn.loops.asyncio as _uv_asyncio

    _uv_asyncio.asyncio_loop_factory = lambda use_subprocess=False: (
        asyncio.SelectorEventLoop
    )

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload="--reload" in sys.argv,
        loop="asyncio",
    )
