# IT Helpdesk System

A service desk application where ticket priority is calculated from impact and urgency instead of being chosen by the person raising the ticket, and SLA timers only count business hours.

I built this to learn how real IT service desks work, and because I wanted a project that wasn't just another CRUD app.

![Ticket queue](docs/queue.png)

---

## Why I built it this way

Most ticket systems I looked at let the user pick a priority from a dropdown. The problem with that is obvious once you think about it: everyone picks "High". Their thing is always the most urgent thing.

Real service desks (following ITIL, which is a set of IT service management best practices) don't ask that. They ask two questions that people can answer honestly:

- **Impact** — how many people are affected? Just you, your team, or everyone?
- **Urgency** — how blocked are you? Can you work around it or not?

Priority comes out of those two answers using a fixed matrix. That's what this app does.

The other thing I wanted to get right was the SLA clock. If a ticket is raised at 5pm on Friday with a 4-hour resolution target, it shouldn't be breached by 9pm Friday night when nobody is at work. And if a technician is waiting three days for the user to reply, that shouldn't count against them either. So the clock only runs during business hours, and it pauses while a ticket is on hold.

---

## What it does

- Raise tickets through a web form or a JSON API
- Priority derived automatically from an ITIL impact/urgency matrix (P1 to P4)
- SLA targets for first response and resolution, calculated in business hours only (8am–6pm, Mon–Fri, Brisbane time)
- SLA clock pauses while a ticket is On Hold and the deadline shifts accordingly
- Queue view sorted by priority then age, with colour-coded SLA countdowns (on track / at risk / breached)
- Status changes go through a state machine, so illegal moves are rejected
- Full audit trail — every action on a ticket is logged with who did it and when
- Three roles: requester, technician, manager
- Requesters can only see their own tickets
- Dashboard with open counts, unassigned count, SLA compliance percentage
- JWT authentication for the API, cookie sessions for the browser
- 34 automated tests

---

## Screenshots

### Ticket detail with audit timeline
![Ticket detail](docs/detail.png)

### Dashboard
![Dashboard](docs/dashboard.png)

---

## The priority matrix

| Impact ↓ / Urgency → | Critical | High | Normal | Low |
|---|---|---|---|---|
| **Organisation** (everyone) | P1 | P1 | P2 | P3 |
| **Department** (a team) | P1 | P2 | P3 | P4 |
| **Individual** (one person) | P2 | P3 | P3 | P4 |

SLA targets, in business hours:

| Priority | First response | Resolution |
|---|---|---|
| P1 | 30 minutes | 4 hours |
| P2 | 2 hours | 8 hours |
| P3 | 4 hours | 24 hours |
| P4 | 8 hours | 72 hours |

The matrix and the targets are both stored as plain Python dictionaries in `app/sla.py`, so if a client wanted different numbers you'd edit one table rather than rewriting any logic.

---

## How the SLA clock works

This was the hardest part of the project and took the longest to get right.

**Business hours only.** A ticket raised Friday at 5pm with a 4-hour target is due Monday at 11am. One hour runs on Friday evening (5–6pm), then the clock stops overnight and over the weekend, and the remaining three hours run from Monday 8am.

**Pausing on hold.** When a technician sets a ticket to On Hold (waiting on the user, or a vendor), the app records the time. When the ticket comes off hold, it works out how much *business* time passed while it was paused and adds that to a running total on the ticket. The resolution deadline is then pushed out by that total.

The paused time has to be added back in business hours too, not calendar hours. If you add 4 calendar hours to a Friday 5pm deadline you get 9pm Friday, which is a time the service desk isn't open. It took me a while to spot that.

**Times are stored in UTC, displayed in Brisbane time.** Storing local time would break the maths if the business calendar ever moved somewhere with daylight saving. The conversion happens in a Jinja filter at display time.

---

## Tech stack

| What | Why |
|---|---|
| **Python 3.12** | Wanted the project to double as scripting practice, since almost every IT support job ad mentions it |
| **FastAPI** | Generates interactive API docs automatically, and the dependency injection made auth and testing much cleaner |
| **SQLAlchemy 2.0** | ORM, so I work with Python objects instead of raw SQL strings. Also parameterises queries, which prevents SQL injection |
| **SQLite** | No database server to install. Only the connection string changes to move to PostgreSQL |
| **Jinja2** | Server-rendered HTML. No JavaScript build step, and it autoescapes output, which stops XSS |
| **bcrypt** | Password hashing with a per-user salt |
| **python-jose** | JWT signing and verification |
| **pytest** | Test suite |
| **Plain CSS** | Hand-written, no framework, so it looks like an internal tool rather than a Bootstrap template |

---

## Getting started

You need Python 3.11 or newer.

```bash
# Clone and enter the project
git clone https://github.com/ItsMe-Amal/IT-Helpdesk-System.git
cd IT-Helpdesk-System

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up your environment file
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# paste that output as SECRET_KEY in .env

# Create the database and add test users
python seed.py

# Run it
uvicorn app.main:app --reload
```

Then open **http://127.0.0.1:8000**

### Test accounts

| Email | Password | Role |
|---|---|---|
| priya@example.com | requester-password-1 | requester |
| tom@example.com | technician-password-1 | technician |
| sam@example.com | manager-password-1 | manager |

These only exist in a local throwaway database. Sign in as Tom to see the full technician view.

### API docs

Interactive API documentation is at **http://127.0.0.1:8000/docs** — FastAPI generates it from the code. Click **Authorize**, log in with one of the accounts above, and you can call every endpoint from the browser.

---

## Project structure

```
app/
├── main.py          # App setup, wires the routers together
├── config.py        # Reads settings from environment variables
├── database.py      # Database connection and session handling
├── models.py        # Database tables: User, Ticket, TicketEvent
├── schemas.py       # Pydantic models — what the API accepts and returns
├── sla.py           # Priority matrix and business-hours SLA logic
├── security.py      # Password hashing and JWT tokens
├── deps.py          # Auth dependencies for API and web
├── crud.py          # Shared helpers: reference numbers, audit logging
├── templating.py    # Jinja setup and custom filters
├── web.py           # HTML page routes
├── routers/
│   ├── auth.py      # /api/auth — login, current user
│   └── tickets.py   # /api/tickets — the JSON API
├── templates/       # HTML templates
└── static/          # CSS
tests/
├── test_sla.py      # SLA and priority logic
└── test_api.py      # API behaviour, auth, and access control
seed.py              # Creates test users
```

The API lives under `/api` and the web pages under `/` so the two don't collide. I found that out the hard way — see the notes further down.

---

## Security

This is the part I cared about most, since I'm coming from a networks and security background.

**Passwords** are hashed with bcrypt and a random salt per user. Hashing the same password twice gives two different hashes. Passwords are never stored or logged in plain text, and the `UserOut` schema has no password field at all, so a hash can't accidentally end up in an API response.

**Nothing important is accepted from the client.** This is the main lesson I took from the project. The client sends only the title, description, category, impact and urgency. Priority is derived by the server. The requester is taken from the access token, not the request body. Status is controlled by the state machine. Early on I had `requester_id` as a field the client sent — which meant anyone could raise a ticket in someone else's name. There's now a test that proves sending a `requester_id` gets ignored.

**Requesters get 404, not 403, for tickets that aren't theirs.** A 403 would confirm that the ticket exists, which is enough to work out how many tickets the system has and which IDs are valid. Returning 404 hides existence entirely.

**Login errors are deliberately vague.** "Incorrect email or password" whether the account exists or not. Different messages would let someone feed in a list of emails and find out which ones are real accounts.

**XSS.** Jinja2 autoescapes everything by default, so a ticket titled `<script>alert(1)</script>` renders as visible text instead of running. I tested this deliberately rather than assuming.

**Cookies.** The browser session cookie is `httpOnly`, so JavaScript can't read the token even if an XSS hole existed, and `SameSite=Lax`, which blocks the basic CSRF attack.

**Secrets.** The signing key comes from an environment variable and `.env` is gitignored. The app refuses to start if `SECRET_KEY` isn't set, rather than falling back to some default — a hardcoded fallback secret is how this kind of thing leaks in real projects.

---

## Testing

```bash
pytest -v
```

34 tests. They run against a fresh in-memory database, so they never touch the real one and every test starts clean. FastAPI's dependency override lets me swap the database with one line, without changing any application code.

The tests are grouped by what they're checking:

- **SLA logic** — the priority matrix, business-hours calculation, weekend and overnight handling
- **Authentication** — unauthenticated requests, invalid tokens, wrong passwords, and that login errors are indistinguishable
- **Server-controlled fields** — that priority and requester can't be set by the client
- **Authorisation** — role enforcement, and that requesters can't read other people's tickets
- **Workflow** — assignment, illegal status transitions, audit trail, first response timing

I tried to write tests that describe business rules rather than implementation details. For example `test_sla_clock_pauses_overnight` says what the system should do, not how it does it — so I could rewrite the SLA function entirely and the test would still tell me whether it's correct.

The tests take about 24 seconds, almost all of it bcrypt hashing passwords in the test fixtures. bcrypt is slow on purpose, so that's the security working rather than a problem to fix.

---

## Things that went wrong

Keeping these in because they're the parts I actually learned from.

**The `.gitignore` didn't cover the database.** I used GitHub's Python template, which ignores `db.sqlite3` (Django's default name) but not `*.db`. I caught it in `git status` before committing. Lesson: templates are a starting point, and you check `git status` before every commit rather than trusting it.

**A routing collision between the API and the web UI.** Both had a `/tickets/{ticket_id}` route. FastAPI matches routes in registration order, so whichever router was registered first won — and the API's version caught `/tickets/new`, treating "new" as a ticket ID and rejecting the request with a 401 because it wanted a bearer token instead of my session cookie.

My first fix was to swap the registration order. That fixed the web page and broke five API tests, which started receiving HTML instead of JSON. Reordering just moves which half is broken. The real fix was to namespace the API under `/api`, so the two never compete for the same path.

The test suite caught this immediately. Without it I would have shipped a broken API and only found out when someone tried to use it.

**bcrypt 5.x doesn't work with passlib.** passlib hasn't been updated for recent bcrypt versions and its version detection breaks. I dropped passlib and called the `bcrypt` library directly — one fewer dependency anyway.

**`default=utcnow` vs `default=utcnow()`.** Without the parentheses, SQLAlchemy calls the function at insert time, which is what you want. With them, you pass one fixed timestamp captured when the file loaded, and every row gets the same value. Easy to miss and hard to notice later.

---

## Known limitations

Being upfront about what isn't finished:

- **No CSRF tokens.** `SameSite=Lax` on the session cookie covers the common attack, but a proper implementation issues a per-session token, puts it in every form, and checks it server-side. This is the biggest gap.
- **Ticket reference numbers have a race condition.** `generate_reference` counts existing tickets and adds one. Two simultaneous requests could both land on the same number. The `unique` constraint on the column means the database rejects the second one — so you get a visible error rather than duplicate references — but the proper fix is a database sequence.
- **Login has a timing side channel.** When the email doesn't exist, the password check is skipped, so the response comes back faster. Someone measuring response times could still enumerate accounts. The fix is to hash a dummy value in that branch so both paths take the same time.
- **Status-change logic is duplicated** between the API router and the web router. It should be pulled out into a single service function that both call.
- **The business-hours calculation steps minute by minute.** For a 72-hour target that's about 20,000 iterations. It runs in milliseconds so it doesn't matter at this scale, but there's a faster approach using whole-day arithmetic plus remainders. I chose the readable version deliberately.
- **No email notifications**, no attachments, no knowledge base, no asset linking.
- **`create_all()` instead of real migrations.** Changing a column means deleting the database file. A production app would use Alembic.
- **`secure=False` on the session cookie**, which is correct for local HTTP but must be `True` behind HTTPS.

---

## What I'd do next

- CSRF tokens on all forms
- Alembic migrations
- Move the shared ticket logic out of both routers into a service layer
- Docker and GitHub Actions CI
- PostgreSQL instead of SQLite
- Email notification on assignment and SLA breach
- Reporting: average resolution time by category, technician workload

---

## What I learned

Going in, I thought the hard part of a ticket system would be the CRUD. It wasn't — that part took a day. The hard parts were the business rules: what priority actually means, when a clock should and shouldn't run, and which fields the client must never be allowed to set.

The other thing that surprised me was how much the tests did for me. I wrote them expecting them to be a chore for the README, and then they caught a real bug I'd introduced while fixing something else.

---

Built by Amal Antony — [GitHub](https://github.com/ItsMe-Amal)