import app  # noqa: F401  (installs the Windows selector event-loop policy)
from fastapi import FastAPI

from app.auth.deps import CurrentUser
from app.auth.routes import router as auth_router
from app.chat.routes import router as chat_router

app = FastAPI(title="AI Assistant Backend")
app.include_router(auth_router)
app.include_router(chat_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/me")
async def me(user: CurrentUser) -> dict[str, str]:
    return {
        "id": str(user.id),
        "email": user.email,
        "nama": user.nama,
        "role": user.role,
        "tenant_id": str(user.tenant_id),
    }
