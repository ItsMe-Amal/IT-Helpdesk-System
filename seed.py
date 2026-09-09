"""Populate the database with a few users for local testing."""
from app.database import SessionLocal, engine, Base
from app import models

Base.metadata.create_all(bind=engine)
db = SessionLocal()

if db.query(models.User).count() == 0:
    db.add_all([
        models.User(name="Priya Nair", email="priya@example.com",
                    hashed_password="placeholder", role="requester",
                    department="Finance"),
        models.User(name="Tom Reid", email="tom@example.com",
                    hashed_password="placeholder", role="technician",
                    department="IT"),
        models.User(name="Sam Chen", email="sam@example.com",
                    hashed_password="placeholder", role="manager",
                    department="IT"),
    ])
    db.commit()
    print("Seeded 3 users.")
else:
    print("Users already exist, skipping.")

db.close()