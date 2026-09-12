from fastapi import FastAPI

from app.database import engine, Base
from app import models
from app.routers import tickets, auth

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="IT Helpdesk System",
    description="ITIL-aligned service desk with impact/urgency priority, "
                "business-hours SLA tracking and role-based access control.",
    version="0.2.0",
)

app.include_router(auth.router)
app.include_router(tickets.router)


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok"}