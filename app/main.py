from fastapi import FastAPI

from app.database import engine, Base
from app import models
from app.routers import tickets

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="IT Helpdesk System",
    description="ITIL-aligned service desk with impact/urgency priority "
                "and business-hours SLA tracking.",
    version="0.1.0",
)

app.include_router(tickets.router)


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok"}