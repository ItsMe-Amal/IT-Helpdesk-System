import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app import models
from app.security import hash_password

REQUESTER = "requester@test.com"
OTHER_REQUESTER = "other@test.com"
TECH = "tech@test.com"
PASSWORD = "test-password-123"


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
        models.User(name="Requester", email=REQUESTER,
                    hashed_password=hash_password(PASSWORD), role="requester"),
        models.User(name="Tech", email=TECH,
                    hashed_password=hash_password(PASSWORD), role="technician"),
        models.User(name="Other", email=OTHER_REQUESTER,
                    hashed_password=hash_password(PASSWORD), role="requester"),
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


def auth(client, email):
    """Log in and return an Authorization header."""
    r = client.post("/api/auth/login", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def new_ticket(client, headers, impact="individual", urgency="normal"):
    return client.post("/api/tickets", headers=headers, json={
        "title": "Laptop will not power on",
        "impact": impact,
        "urgency": urgency,
    })


# ---------- Authentication ----------

def test_unauthenticated_request_rejected(client):
    assert client.get("/api/tickets").status_code == 401


def test_invalid_token_rejected(client):
    r = client.get("/api/tickets", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_login_returns_bearer_token(client):
    r = client.post("/api/auth/login", data={"username": TECH, "password": PASSWORD})
    assert r.status_code == 200
    assert r.json()["token_type"] == "bearer"


def test_wrong_password_rejected(client):
    r = client.post("/api/auth/login", data={"username": TECH, "password": "wrong"})
    assert r.status_code == 401


def test_login_errors_are_indistinguishable(client):
    """No username enumeration: unknown email and wrong password look identical."""
    unknown = client.post("/api/auth/login",
                          data={"username": "nobody@test.com", "password": PASSWORD})
    wrong = client.post("/api/auth/login",
                        data={"username": TECH, "password": "wrong"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_me_returns_current_user_without_password(client):
    r = client.get("/api/auth/me", headers=auth(client, TECH))
    assert r.json()["email"] == TECH
    assert "hashed_password" not in r.json()


# ---------- Server-controlled fields ----------

def test_create_ticket_derives_priority(client):
    r = new_ticket(client, auth(client, REQUESTER), "organisation", "critical")
    assert r.status_code == 201
    assert r.json()["priority"] == 1


def test_client_cannot_set_priority(client):
    r = client.post("/api/tickets", headers=auth(client, REQUESTER), json={
        "title": "Trying to jump the queue",
        "impact": "individual", "urgency": "low",
        "priority": 1,
    })
    assert r.json()["priority"] == 4


def test_requester_taken_from_token_not_payload(client):
    """Even if a client sends requester_id, the server ignores it."""
    headers = auth(client, REQUESTER)
    r = client.post("/api/tickets", headers=headers, json={
        "title": "Raising this as somebody else",
        "impact": "individual", "urgency": "low",
        "requester_id": 2,
    })
    assert r.json()["requester"]["email"] == REQUESTER


def test_reference_is_generated(client):
    r = new_ticket(client, auth(client, REQUESTER))
    assert r.json()["reference"].startswith("INC-")


def test_short_title_rejected(client):
    r = client.post("/api/tickets", headers=auth(client, REQUESTER), json={
        "title": "hi", "impact": "individual", "urgency": "low",
    })
    assert r.status_code == 422


# ---------- Authorisation ----------

def test_requester_cannot_assign_tickets(client):
    new_ticket(client, auth(client, REQUESTER))
    r = client.patch("/api/tickets/1/assign", headers=auth(client, REQUESTER),
                     json={"assignee_id": 2})
    assert r.status_code == 403


def test_requester_cannot_change_status(client):
    new_ticket(client, auth(client, REQUESTER))
    r = client.patch("/api/tickets/1/status", headers=auth(client, REQUESTER),
                     json={"status": "in_progress"})
    assert r.status_code == 403


def test_requester_cannot_read_another_users_ticket(client):
    """IDOR defence: 404, not 403, so ticket existence is not confirmed."""
    new_ticket(client, auth(client, REQUESTER))
    r = client.get("/api/tickets/1", headers=auth(client, OTHER_REQUESTER))
    assert r.status_code == 404


def test_requester_queue_is_scoped_to_own_tickets(client):
    new_ticket(client, auth(client, REQUESTER))
    r = client.get("/api/tickets", headers=auth(client, OTHER_REQUESTER))
    assert r.json() == []


def test_technician_sees_all_tickets(client):
    new_ticket(client, auth(client, REQUESTER))
    r = client.get("/api/tickets", headers=auth(client, TECH))
    assert len(r.json()) == 1


# ---------- Workflow ----------

def test_assign_sets_status(client):
    new_ticket(client, auth(client, REQUESTER))
    r = client.patch("/api/tickets/1/assign", headers=auth(client, TECH),
                     json={"assignee_id": 2})
    assert r.json()["status"] == "assigned"


def test_cannot_assign_to_a_requester(client):
    new_ticket(client, auth(client, REQUESTER))
    r = client.patch("/api/tickets/1/assign", headers=auth(client, TECH),
                     json={"assignee_id": 1})
    assert r.status_code == 400


def test_illegal_transition_rejected(client):
    new_ticket(client, auth(client, REQUESTER))
    r = client.patch("/api/tickets/1/status", headers=auth(client, TECH),
                     json={"status": "closed"})
    assert r.status_code == 409


def test_audit_trail_records_the_actor(client):
    new_ticket(client, auth(client, REQUESTER))
    client.patch("/api/tickets/1/assign", headers=auth(client, TECH),
                 json={"assignee_id": 2})
    events = client.get("/api/tickets/1", headers=auth(client, TECH)).json()["events"]
    assigned = [e for e in events if e["event_type"] == "assigned"][0]
    assert assigned["actor"]["email"] == TECH


def test_technician_comment_sets_first_response(client):
    new_ticket(client, auth(client, REQUESTER))
    client.post("/api/tickets/1/comments", headers=auth(client, TECH),
                json={"body": "Looking into it now."})
    r = client.get("/api/tickets/1", headers=auth(client, TECH))
    assert r.json()["first_response_at"] is not None


def test_requester_comment_does_not_set_first_response(client):
    """Only a technician replying counts as the first response."""
    new_ticket(client, auth(client, REQUESTER))
    client.post("/api/tickets/1/comments", headers=auth(client, REQUESTER),
                json={"body": "Any update?"})
    r = client.get("/api/tickets/1", headers=auth(client, REQUESTER))
    assert r.json()["first_response_at"] is None


def test_queue_orders_by_priority(client):
    headers = auth(client, REQUESTER)
    new_ticket(client, headers, "individual", "low")
    new_ticket(client, headers, "organisation", "critical")
    priorities = [t["priority"] for t in client.get("/api/tickets", headers=headers).json()]
    assert priorities == sorted(priorities)


def test_missing_ticket_returns_404(client):
    assert client.get("/api/tickets/999", headers=auth(client, TECH)).status_code == 404