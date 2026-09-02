import app  # noqa: F401  (installs the Windows selector event-loop policy)
from fastapi import FastAPI

app = FastAPI(title="AI Assistant Backend")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
