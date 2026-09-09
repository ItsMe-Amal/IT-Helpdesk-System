import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app import models


@pytest.fixture
def client():
    """A test client backed by a fresh in-memory database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestSession()
    db.add_all([
        models.User(name="Requester", email="r@test.com",
                    hashed_password="x", role="requester"),
        models.User(name="Tech", email="t@test.com",
                    hashed_password="x", role="technician"),
    ])
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    db.close()


def _new_ticket(client, impact="individual", urgency="normal"):
    return client.post("/tickets", json={
        "title": "Laptop will not power on",
        "impact": impact,
        "urgency": urgency,
        "requester_id": 1,
    })


def test_create_ticket_derives_priority(client):
    r = _new_ticket(client, "organisation", "critical")
    assert r.status_code == 201
    assert r.json()["priority"] == 1


def test_reference_is_generated(client):
    r = _new_ticket(client)
    assert r.json()["reference"].startswith("INC-")


def test_client_cannot_set_priority(client):
    """Priority is server-controlled; any client value is ignored."""
    r = client.post("/tickets", json={
        "title": "Trying to jump the queue",
        "impact": "individual",
        "urgency": "low",
        "requester_id": 1,
        "priority": 1,
    })
    assert r.json()["priority"] == 4


def test_short_title_rejected(client):
    r = client.post("/tickets", json={
        "title": "hi", "impact": "individual",
        "urgency": "low", "requester_id": 1,
    })
    assert r.status_code == 422


def test_assign_sets_status(client):
    _new_ticket(client)
    r = client.patch("/tickets/1/assign", json={"assignee_id": 2})
    assert r.json()["status"] == "assigned"


def test_cannot_assign_to_requester(client):
    _new_ticket(client)
    r = client.patch("/tickets/1/assign", json={"assignee_id": 1})
    assert r.status_code == 400


def test_illegal_transition_rejected(client):
    _new_ticket(client)
    r = client.patch("/tickets/1/status", json={"status": "closed"})
    assert r.status_code == 409


def test_audit_trail_records_actions(client):
    _new_ticket(client)
    client.patch("/tickets/1/assign", json={"assignee_id": 2})
    events = client.get("/tickets/1").json()["events"]
    types = [e["event_type"] for e in events]
    assert "created" in types and "assigned" in types


def test_technician_comment_sets_first_response(client):
    _new_ticket(client)
    client.post("/tickets/1/comments",
                json={"body": "Looking into it now.", "author_id": 2})
    assert client.get("/tickets/1").json()["first_response_at"] is not None


def test_queue_orders_by_priority(client):
    _new_ticket(client, "individual", "low")          # P4
    _new_ticket(client, "organisation", "critical")   # P1
    priorities = [t["priority"] for t in client.get("/tickets").json()]
    assert priorities == sorted(priorities)


def test_missing_ticket_returns_404(client):
    assert client.get("/tickets/999").status_code == 404