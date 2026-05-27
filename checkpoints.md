# Here are the exact verification steps.

Pre-flight checks

1. Python version
bashpython --version
# must be 3.12+

2. Install dependencies
bashcd agent
uv sync

3. Docker is running
bashdocker info
# must not error

4. Copy and fill env
bashcp .env.example .env
# fill in at minimum:
# GITHUB_WEBHOOK_SECRET=any-string-for-now
# GITHUB_TOKEN=your-real-token
# LLM_PROVIDER=anthropic (or whichever you have a key for)
# ANTHROPIC_API_KEY=your-key

Start infrastructure

5. Start Postgres and Redis
bashdocker compose up -d
# wait ~5 seconds then verify:
docker compose ps
# both postgres and redis should show "running"

6. Verify Postgres connection
bashdocker exec -it agent-postgres-1 psql -U agent -d agent -c "\dt"
# should connect (tables empty for now, migrations not yet run)

7. Verify Redis connection
bashdocker exec -it agent-redis-1 redis-cli ping
# should return: PONG

Run database migrations

8. Run Alembic migrations
bashuv run alembic upgrade head
# should print: Running upgrade -> xxxx, OK

9. Verify tables were created
bashdocker exec -it agent-postgres-1 psql -U agent -d agent -c "\dt"
# should show: agent_runs table

Run the test suite

10. Run all unit tests
bashuv run pytest tests/ -v
# all tests should pass
# no Docker, no real API calls needed — everything is mocked

11. Run tests with coverage
bashuv run pytest tests/ --cov=app --cov-report=term-missing

Start the FastAPI server

12. Start uvicorn
bashuv run uvicorn app.main:app --reload --port 8000

13. Hit the health endpoint
bashcurl http://localhost:8000/health
# expected: {"status": "ok", ...}

14. Check the OpenAPI docs load
bashopen http://localhost:8000/docs
# or just visit in browser — should show all routes

Test the webhook endpoint manually

15. Send a fake webhook with correct HMAC
bash# replace SECRET with whatever you set in .env
SECRET="your-github-webhook-secret"
PAYLOAD='{"action":"labeled","issue":{"number":1,"title":"Fix null check","body":"get_user raises","state":"open","html_url":"https://github.com/org/repo/issues/1","user":{"login":"user","id":1},"labels":[{"name":"agent-resolve"}]},"repository":{"id":1,"full_name":"org/repo","private":false,"clone_url":"https://github.com/org/repo.git","default_branch":"main"},"sender":{"login":"user","id":1}}'

SIG="sha256=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')"

curl -X POST http://localhost:8000/api/v1/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: $SIG" \
  -H "X-GitHub-Event: issues" \
  -H "X-GitHub-Delivery: test-delivery-001" \
  -d "$PAYLOAD"

# expected: {"message": "Issue queued for processing", "run_id": "...", "delivery_id": "..."}

16. Verify AgentRun was created in DB
bashdocker exec -it agent-postgres-1 psql -U agent -d agent \
  -c "SELECT id, repo_full_name, issue_number, status FROM agent_runs;"
# should show one row with status=pending

17. Send same payload again (idempotency check)
bash# re-run the exact same curl from step 15
# expected: {"message": "Already processing", ...} — no duplicate row created

18. Test invalid HMAC is rejected
bashcurl -X POST http://localhost:8000/api/v1/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=invalidsignature" \
  -H "X-GitHub-Event: issues" \
  -H "X-GitHub-Delivery: test-delivery-002" \
  -d "$PAYLOAD"
# expected: 401 {"error": "http_error", "detail": "Invalid webhook signature"}

Start the Celery worker

19. Start worker in a second terminal
bashuv run celery -A app.workers.celery_app worker --loglevel=info
# should print: ready. and show the registered task: agent.process_issue

20. Trigger a real task end-to-end
bash# re-run step 15 with a new delivery ID:
# change X-GitHub-Delivery to test-delivery-003
# the worker terminal should show:
# pipeline.start → intake.parsing → ... → pipeline.intake_complete

21. Verify AgentRun status updated
bashdocker exec -it agent-postgres-1 psql -U agent -d agent \
  -c "SELECT id, status, intent, risk_level, retry_count FROM agent_runs ORDER BY created_at DESC LIMIT 5;"
# status should have moved from pending → planning → executing (or aborted if risk high)

LLM provider check

22. Verify your chosen provider key works
bash# quick one-liner outside the app:
python3 -c "
import asyncio
from app.llm import get_llm_provider, LLMMessage, MessageRole

async def test():
    llm = get_llm_provider()
    r = await llm.complete([LLMMessage(role=MessageRole.user, content='Say hello in 5 words.')])
    print(r.content)

asyncio.run(test())
"
# should print a 5-word response from your provider

What each passing checkpoint confirms
StepConfirms1–4Environment set up correctly5–7Postgres and Redis reachable8–9Schema migrations work, AgentRun table exists10–11All business logic unit tests pass12–14FastAPI app starts, routing works15–16Webhook validation + DB write works17Idempotency (no duplicate runs) works18HMAC rejection works19–21Celery worker picks up jobs, intake pipeline runs22LLM provider key is valid and reachable
If all 22 pass, the system is healthy through Phase 3.