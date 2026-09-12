"""Populate the database with test users. Local development only.

Passwords here are deliberately weak and public — never reuse this
pattern outside a throwaway local database.
"""
from app.database import SessionLocal, engine, Base
from app import models
from app.security import hash_password

Base.metadata.create_all(bind=engine)
db = SessionLocal()

if db.query(models.User).count() == 0:
    db.add_all([
        models.User(name="Priya Nair", email="priya@example.com",
                    hashed_password=hash_password("requester-password-1"),
                    role="requester", department="Finance"),
        models.User(name="Tom Reid", email="tom@example.com",
                    hashed_password=hash_password("technician-password-1"),
                    role="technician", department="IT"),
        models.User(name="Sam Chen", email="sam@example.com",
                    hashed_password=hash_password("manager-password-1"),
                    role="manager", department="IT"),
    ])
    db.commit()
    print("Seeded 3 users.")
else:
    print("Users already exist, skipping.")

db.close()