from fastapi import FastAPI

from app.database import engine, Base
from app import models

Base.metadata.create_all(bind=engine)

app = FastAPI(title="IT Helpdesk System")


@app.get("/")
def read_root():
    return {"status": "Helpdesk API is running"}