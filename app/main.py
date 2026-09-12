from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import engine, Base
from app import models
from app.routers import tickets, auth
from app import web

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="IT Helpdesk System",
    description="ITIL-aligned service desk with impact/urgency priority, "
                "business-hours SLA tracking and role-based access control.",
    version="0.3.0",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(tickets.router)
app.include_router(web.router)


@app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok"}