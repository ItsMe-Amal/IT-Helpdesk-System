from fastapi import FastAPI

app = FastAPI(title="IT Helpdesk System")

@app.get("/")
def read_root():
    return {"status": "Helpdesk API is running"}