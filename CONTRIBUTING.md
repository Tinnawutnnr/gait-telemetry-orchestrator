# Contributing to Gait Telemetry Orchestrator

This document lays out the engineering standards and workflows we follow.

## 🛠 Development Setup

To ensure parity between environments and avoid "it works on my machine" issues, please follow the initial development setup exactly:

1. **Python Environment:**
   Initialize an isolated virtual environment (we mandate Python 3.11+).
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Docker Infrastructure:**
   The backend relies heavily on asyncpg and PostgreSQL 16. Spin up the local development database with Docker Compose:
   ```bash
   docker compose up -d
   ```

3. **Database Pre-flight:**
   Apply our database migrations sequentially to sync your local environment:
   ```bash
   alembic upgrade head
   ```

## 📝 Pull Request Process

Every PR submitted must cleanly pass our core CI/CD gates. The lifecycle of a contribution is:

1. **Linting & Formatting:** 
   Our CI strictly enforces `Ruff`. Run the linter locally and resolve all surface-level warnings before committing.
   ```bash
   ruff format .
   ruff check --fix .
   ```
2. **Testing Validation:**
   We mandate a **100% pass rate** on the testing suite. Tests are executed via `pytest` operating against an ephemeral test database (using the `.env.test` configuration).
   ```bash
   pytest -v
   ```
3. **Peer Review:** 
   Ensure your Code Owner/Architect approves structural and logical alterations.

## 🗄️ Database Changes (Alembic)

**Direct SQL execution against production or staging environments is strictly prohibited.**

Any modification to the Database Schema (e.g., adding a table, adding a declarative partition, indexing strategies) **MUST** be implemented natively through SQLAlchemy ORM revisions followed by an Alembic migration script. Ensure both `upgrade()` and `downgrade()` functions are completely idempotent.

## ⚡ Asynchronous Standards

The core pipeline operates on an async execution model. **There must be ABSOLUTELY NO blocking synchronous I/O operations residing within the FastAPI event loop.** 

* Always use `AsyncSession` for all SQLAlchemy transactions (`await db.execute(...)`, `await db.scalar(...)`).
* Always resolve external HTTP traffic with asynchronous REST clients (`httpx.AsyncClient`).

## 🧠 ML / Signal Processing

Because this system orchestrates real-time patient anomaly scoring (using SciPy filtering and Scikit-Learn LOF), algorithm updates are inherently computationally expensive. 
* Any PR modifying the core signal processing pipelines should include **performance profiling** metrics (CPU cycles, RAM footprint overhead). Ensure the sliding-window operations maintain sub-millisecond execution times.

## 🌿 Git Workflow & Branching

We champion descriptive consistency to maintain a clean Git history:
* **Branch Names:** Prefix branches natively (e.g., `feat/add-lof-model`, `fix/partition-key-bug`, `chore/bump-postgres`).
* **Commit Messages:** Adopt the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification. A descriptive, imperative tone (e.g., `feat: establish asyncpg connection pool`) acts as invaluable engineering context.
