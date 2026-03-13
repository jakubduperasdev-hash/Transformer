# Production Roadmap: From MVP to European SaaS (80M+ tokens/day)

## Is the current project appropriate?

**Short answer: No.** The current setup is a solid **MVP/prototype**. It is not suitable as-is for a European SaaS handling **80M+ tokens/day** in terms of scale, reliability, or compliance.

Below is why, and what to change.

---

## 1. Scale (80M+ tokens/day)

**Rough scale**
- 80M tokens/day ≈ **3.3M tokens/hour** ≈ **55k tokens/minute** (average).
- If each “turn” is ~100–200 tokens (user + model), that’s on the order of **hundreds of thousands of chat turns per day**.
- Your current benchmark: **~3–4 s per reply on CPU**, one request at a time per process ⇒ **~15–25 replies/min per process** ⇒ you’d need **hundreds of processes** to reach that throughput on CPU alone.

**Current limitations**

| Area | Current | Issue at 80M+ tokens/day |
|------|--------|---------------------------|
| **Inference** | Single process, model in API process, no batching | One request at a time; no GPU batching; cannot scale out. |
| **Database** | SQLite, single file | Single writer, no replication, not for high concurrency or distributed systems. |
| **API** | One FastAPI app, no queue | All requests hit the model directly; under load you get timeouts and no backpressure. |
| **Deployment** | Single machine implied | No horizontal scaling, no separation of API vs inference. |

**Direction for production**

- **Separate inference from API**
  - Move model to a **dedicated inference service** (e.g. **vLLM**, **TGI**, **Sagemaker**, or similar) that:
    - Runs on **GPU** and supports **continuous batching** (many requests in one batch).
    - Serves 80M+ tokens/day with far fewer nodes than “one model per API process”.
  - Your **current codebase becomes the “app”**: auth, routing, tenant/usage, and “which model/endpoint to call.” It **calls** the inference service over the network instead of loading the model in-process.

- **Queue + workers (if you keep “your” inference in-house)**
  - API receives a request → enqueue job (e.g. **Redis** + **Celery** or **RabbitMQ**).
  - Worker(s) run the model, write result to DB/cache; client polls or uses **WebSocket/SSE** for streaming.
  - This gives backpressure, retries, and decouples API from inference so you can scale each independently.

- **Database**
  - Replace SQLite with **PostgreSQL** (or similar): connection pooling, replication, backups, point-in-time recovery.
  - Use it for: users, tenants, chat metadata, and (if you store it) conversation history. Optionally use **Redis** for rate limits, caches, and queues.

- **Horizontal scaling**
  - Run **multiple API instances** behind a **load balancer**.
  - Run **multiple inference workers** or a **scalable inference cluster** (e.g. vLLM multi-node). Scale based on queue depth or token throughput.

---

## 2. Reliability and operations

**Current gaps**

- No **health checks** (e.g. /health that verifies DB and inference).
- No **rate limiting** or **per-tenant quotas** (critical for 80M tokens and fair use).
- No **structured logging** (request id, tenant, token count) for debugging and billing.
- **Secrets** (e.g. JWT) in env is good, but no rotation or vault story.
- Single process ⇒ no **graceful shutdown** or **drain**.

**Direction for production**

- Add **liveness/readiness** probes and **graceful shutdown**.
- **Rate limiting**: per user and per tenant (e.g. tokens/day or requests/min), using Redis or DB.
- **Structured logs** (JSON) with tenant_id, user_id, request_id, token counts.
- **Metrics**: latency (p50/p95/p99), tokens/sec, errors; export to **Prometheus**/Grafana or your provider.
- Use a **secrets manager** (e.g. AWS Secrets Manager, HashiCorp Vault) and **rotate** JWT and DB credentials.

---

## 3. European SaaS and compliance

**GDPR and EU expectations**

- **Lawful basis and consent** for processing (e.g. chat content, logs).
- **Right to erasure**: delete all data for a user/tenant (chat history, logs, backups).
- **Data portability**: export user/tenant data in a machine-readable format.
- **DPA** (Data Processing Agreement) and **sub-processors** (e.g. inference provider, DB, cloud).
- **Data residency**: many customers will require **EU-only** (hosting and, where applicable, inference in EU).

**Current gaps**

- No **user/tenant deletion** flow (only app-level; DB and backups not covered).
- No **export** of user data.
- No **audit log** of who accessed what, or of data processing events.
- JWT and DB in one app; no clear **tenant isolation** or **billing** by tenant/token.

**Direction for production**

- **Tenant model**: every user belongs to a **tenant** (company); isolate data and usage by tenant.
- **Delete user**: API that deletes user + all their chats (and any PII in logs); extend to **purge from backups** (retention policy).
- **Export**: API (or async job) that returns all data for a user/tenant in a standard format (e.g. JSON/NDJSON).
- **Audit log**: who did what (login, delete, export, admin actions); store in DB or dedicated store, with retention.
- **Privacy policy / consent**: capture consent and lawful basis; store with user/tenant.
- **Hosting**: run API, DB, queue, and (if possible) inference in **EU regions**; document sub-processors and DPAs.

---

## 4. Security

**Current vs production**

- **Auth**: JWT is fine; add **refresh tokens**, **short-lived access tokens**, and **secure cookie** options for web.
- **Secrets**: no hardcoded secrets; use env + **secrets manager** in production.
- **HTTPS only**, **security headers** (CSP, HSTS, etc.).
- **Input/output**: validate and sanitize; log without storing unnecessary PII; consider **content filtering** for abuse and compliance.

---

## 5. Suggested architecture (high level)

```
                    [EU region]
  Clients → [Load balancer] → [API layer: FastAPI × N]
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
              [PostgreSQL]      [Redis: cache,    [Queue: e.g. Redis]
               (users, tenants,   rate limit,        or RabbitMQ]
                chats, audit)      sessions)
                    │                 │
                    └────────┬────────┘
                             ▼
              [Inference: vLLM / TGI / managed endpoint]
              (GPU, batching, auto-scale, EU if required)
```

- **This repo** = API layer (auth, tenants, chat routing, streaming proxy, usage, delete/export).
- **Inference** = separate service or managed LLM API; API layer sends prompts and streams responses.
- **DB** = PostgreSQL; **Redis** for rate limits and cache; **queue** if you run your own inference workers.

---

## 6. Summary: is the project “proper” and how to make it so

| Dimension | Current | To be “proper” for 80M+ tokens/day EU SaaS |
|-----------|--------|--------------------------------------------|
| **Scale** | Single process, SQLite, in-process model | Separate inference (vLLM/TGI/managed), PostgreSQL, queue, horizontal scaling |
| **Reliability** | No rate limits, no metrics, single point of failure | Rate limits, quotas, health checks, metrics, multi-instance + LB |
| **Compliance** | No delete/export, no audit, no tenant model | GDPR: delete, export, audit log, tenant isolation, EU residency |
| **Security** | Basic JWT, env secrets | Short-lived tokens, secrets manager, HTTPS, headers |

**Conclusion:** The current chatbot platform is **not appropriate** as-is for a European SaaS with 80M+ tokens/day. It is a good **foundation** for product and UX (auth, streaming, chat, DB). To make it **appropriate** for that company:

1. **Use a dedicated inference service** (vLLM, TGI, or managed) with batching and GPU in EU if required.
2. **Replace SQLite with PostgreSQL** and add **Redis** (rate limit, cache, optional queue).
3. **Introduce tenants** and **usage/token metering** (per tenant/day).
4. **Add GDPR-oriented features**: user/tenant delete, export, audit log, consent; host in EU.
5. **Add production ops**: health checks, rate limiting, structured logging, metrics, secrets manager.

If you want, next step can be a **concrete checklist** (per file or per component) for this repo (e.g. “replace SQLite with PostgreSQL here”, “add tenant_id here”, “add /export and /delete-user here”) so the project can be evolved step by step toward this target.

---

## 7. Implemented in this repo

The following production-oriented features are **already implemented** in this codebase:

| Area | Implemented |
|------|-------------|
| **Database** | PostgreSQL supported when `DATABASE_URL` is set; SQLite fallback. Connection check in health. |
| **Tenants** | `tenants` table; `users.tenant_id`; default tenant; tenant isolation for usage. |
| **Usage / billing** | `tenant_daily_usage` (per tenant, per day: `request_count`, `token_count`). `record_usage()` called after each chat. |
| **Audit log** | `audit_log(tenant_id, user_id, action, details)` for login, export, delete, etc. |
| **GDPR** | `DELETE /api/users/me` (right to erasure), `GET /api/users/me/export` (data portability). |
| **Rate limiting** | Per-user limits; **Redis** when `REDIS_URL` is set, in-memory otherwise. Config: `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW`. |
| **Health** | `GET /api/health`: DB check; when `INFERENCE_API_URL` is set, inference check (503 if inference down). |
| **Logging** | Request-ID middleware, structured JSON logs. |
| **Inference** | Optional **external** inference: set `INFERENCE_API_URL` (OpenAI-compatible or vLLM/TGI). API uses `inference_client` when set; otherwise local `romatic_chatbot`. Retries and circuit breaker when using external inference. |
| **Graceful shutdown** | Lifespan shutdown logs and brief drain delay. |
| **Per-tenant quotas** | Optional daily token/request limits per tenant (`TENANT_DAILY_TOKEN_LIMIT`, `TENANT_DAILY_REQUEST_LIMIT`). Enforced before chat/stream; 429 when exceeded. |
| **DB connection pooling** | PostgreSQL uses `ThreadedConnectionPool` when `DATABASE_URL` is set (`PG_POOL_MIN`, `PG_POOL_MAX`). |
| **Metrics** | `GET /metrics` exposes Prometheus counters: `http_requests_total`, `http_request_duration_seconds_*`, `chat_tokens_total`, `chat_errors_total`. |
| **Refresh tokens** | Login returns short-lived access token (default 15 min) and refresh token (7 days). `POST /api/refresh` exchanges refresh token for new access token. |
| **Consent / lawful basis** | Optional `consent_at` and `lawful_basis` on register; stored on user and included in GDPR export. |

**Still optional / future**

- **Redis** for rate limiting: set `REDIS_URL` to use it.
- **Secrets manager** and JWT rotation (env is in place; rotation not implemented).
- **Queue + workers** if you run in-house inference (API can call external API or local model; no queue in repo).
- **Frontend**: use refresh token to obtain new access token on 401 (e.g. call `POST /api/refresh` and retry).

---

## 8. Assessment: European SaaS at 80M+ tokens/day

**With external inference (e.g. vLLM) and the features above in place, this project is in good shape for a European SaaS that aims to handle 80M+ tokens/day.**

| Dimension | Status |
|-----------|--------|
| **Scale** | API is separate from inference; use vLLM/TGI (or managed) with batching and GPU. PostgreSQL + pooling; optional Redis for rate limits across instances. Run multiple API instances behind a load balancer. |
| **Reliability** | Rate limits, per-tenant quotas, health (DB + inference), retries and circuit breaker for inference, metrics, graceful shutdown. |
| **Compliance** | GDPR: delete, export, audit log, consent/lawful basis; tenant isolation and usage metering. |
| **Security** | Short-lived access tokens, refresh tokens, env-based secrets. |

**Response time measurement**

- **Local model**: `python benchmark_chat.py` measures cold/warm response time for the in-process chatbot (no API).
- **API (simulated)**: `python benchmark_api_response_time.py` sends real HTTP requests to `POST /api/chat`, reports **average**, **p50**, and **p95** response time. Use `--base-url` and `--requests` as needed. Requires the API to be running and a working chat backend (local model or `INFERENCE_API_URL`).
- **Production**: `GET /metrics` exposes `http_request_duration_seconds_sum` and `_count` per path; from Prometheus you can compute average (and percentiles if you use a histogram in the future).
