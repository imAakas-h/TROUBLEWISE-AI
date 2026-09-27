# Smart Guided Troubleshooting Engine
### Samsung PRISM Generative AI Hackathon 3.0 — Theme 02

An intelligent REST API that transforms vague Galaxy device complaints into precise, actionable troubleshooting plans with validated deeplinks to Samsung Settings. Every step is grounded in Samsung's official reference documentation—no hallucinations, no fabricated steps.

**Example:**
```
Input:  "My Galaxy Z Flip 6 screen flickers and goes blank"

Output: 1. Inspect for physical damage         (SIIS-grounded diagnostic check)
```

---

## Quick Navigation

- [How to Start the App](#3-how-to-start-the-app) ⚡ **Start here!**
- [What This Is](#1-what-this-actually-is)
- [Architecture](#2-architecture)
- [Tech Stack](#4-tech-stack)
- [Key Features & Differentiators](#5-usp--whats-actually-different-here)

---

## 1. What this actually is

The **graded deliverable is a REST API** — `POST /v1/troubleshoot`,
`GET /health` — returning JSON validated against the official `schema.py`
contract. That's not our framing; it's what the official brief and the
evaluation rubric say explicitly (see `docs/specification.md`). Everything
else in this repo — the frontend, the optional AI layer — exists to make the
engine demoable and pleasant to use, and none of it is required for, or
graded by, the official evaluator.

We're explicit about this because it shapes every decision below: the
backend is the product; the frontend is a window onto it.

---

## 2. Architecture
<img width="1835" height="717" alt="image" src="https://github.com/user-attachments/assets/11bab7dc-f5ef-4fb0-939f-d21e6c97f453" />



```

Full stage-by-stage rationale, including three real bugs found and fixed
during development, is in `docs/architecture.md` and
`docs/implementation-plan.md`.

---

## 3. How to start the app

### Prerequisites

- **Python 3.8+** installed on your system
- **pip** (Python package manager)
- **Internet connection** (for installing dependencies and optional Groq API)

### Step 1: Clone/Download the project

If you haven't already, clone or download this repository to your local machine.

### Step 2: Set up Python virtual environment (recommended)

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `fastapi` - Web framework for the API
- `uvicorn` - ASGI server
- `pydantic` - Data validation
- `rank_bm25` - Search ranking
- `requests` - HTTP library
- `python-dotenv` - Environment variable management

### Step 4: Start the backend server

```bash
uvicorn app.main:app --reload
```

The server will start on `http://localhost:8000`

**Verify it's running:**
- Health check: `GET http://localhost:8000/health` → `{"status": "ok"}`
- Interactive API docs (Swagger UI): Open `http://localhost:8000/docs` in your browser
- Main endpoint: `POST http://localhost:8000/v1/troubleshoot`

The engine pre-warms its cache with the 20 supplied seed scenarios on
startup, so those (and near-exact rewordings of them) answer in under a
millisecond.

### Step 5: Start the frontend (optional, for visual demo)

Open a **new terminal window** (keep the backend running in the first one):

```bash
# Windows
cd frontend
python -m http.server 5500

# macOS/Linux
cd frontend
python3 -m http.server 5500
```

Then open `http://localhost:5500` in your browser (works on mobile browsers too).

**Mobile-first design:** The frontend is fully responsive and works great on phones. You can open
the URL on your mobile device's browser for a native-app-like experience.

**Why web instead of native Android:**
- Works immediately in any mobile browser—no APK install, no Play Store, no signing
- Can be tested and verified in this development environment
- Perfect for hackathon demos (scan QR code → instant access)
- Zero build toolchain complexity

**Note:** The frontend is a plain static HTML/CSS/JS page with no build step. It calls the backend
via `fetch()`. If your backend isn't on `localhost:8000`, either:
- Edit `API_BASE` at the top of `frontend/app.js`, OR
- Open the page with `?api=http://host:port` appended to the URL

### Step 6: Optional - Enable AI enhancement with Groq

The app works fully without this, but for enhanced paraphrasing and polished descriptions:

```bash
# Copy the example environment file
copy .env.example .env     # Windows
cp .env.example .env       # macOS/Linux

# Edit .env and add your Groq API key
# Get a free key at https://console.groq.com (no credit card needed)
```

Edit the `.env` file:
```
GROQ_API_KEY=your_actual_key_here
```

Restart the backend server (Ctrl+C, then `uvicorn app.main:app --reload` again).

With a key set, `/v1/troubleshoot` responses will use AI for richer paraphrases and polished
descriptions, reporting `"model": "rule-based-extraction-v1+groq"` instead of the deterministic-only
label. Everything is still validated against the schema afterward.

### Quick Start Commands (Summary)

```bash
# Terminal 1 - Backend (required)
pip install -r requirements.txt
uvicorn app.main:app --reload

# Terminal 2 - Frontend (optional, for visual demo)
cd frontend
python -m http.server 5500

# Browser
# Backend API docs: http://localhost:8000/docs
# Frontend UI: http://localhost:5500
```

### Testing the API

#### Available Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check - returns `{"status": "ok"}` |
| `GET` | `/docs` | Interactive Swagger UI for testing APIs |
| `POST` | `/v1/troubleshoot` | Main endpoint - converts query to troubleshooting plan |
| `POST` | `/v1/guidance` | AI guidance layer (optional enhancement) |
| `POST` | `/v1/feedback` | Record user feedback for experience memory |

#### Testing Methods

**Using the Swagger UI** (easiest):
1. Go to `http://localhost:8000/docs`
2. Click on `POST /v1/troubleshoot`
3. Click "Try it out"
4. Enter a query like: `{"query": "My screen flickers and goes blank"}`
5. Click "Execute"

**Using curl**:
```bash
curl -X POST http://localhost:8000/v1/troubleshoot \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"My Galaxy Z Flip 6 screen flickers\"}"
```

**Using Python**:
```python
import requests
response = requests.post(
    "http://localhost:8000/v1/troubleshoot",
    json={"query": "Battery drains too fast"}
)
print(response.json())
```

### Run the benchmark (reproduces every number in this README)

```bash
python -m tests.run_benchmark
```

### Troubleshooting

**Port 8000 already in use:**
```bash
uvicorn app.main:app --reload --port 8001
# Update API_BASE in frontend/app.js to http://localhost:8001
```

**Module not found errors:**
Make sure you're in the project root directory and have activated the virtual environment.

**CORS errors in frontend:**
The backend is configured with permissive CORS for local development. If you still see errors,
check that both servers are running and the API_BASE URL in `frontend/app.js` matches your backend.

---

## 4. Tech stack

| Layer | Choice | Why |
|---|---|---|
| API framework | FastAPI + Pydantic v2 | matches `schema.py` exactly; free interactive docs (`/docs`) doubles as a demo UI |
| Server | Uvicorn | standard FastAPI ASGI server |
| Retrieval | `rank_bm25` + weighted lexical/topic overlap | lightweight retrieval over SIIS text and deeplink metadata |
| Deeplink ranking | BM25 + local TF-IDF | no hosted embedding or LLM required |
| Fast path | canonical exact-key in-memory cache | avoids unsafe fuzzy cache matches; common wording variants normalize together |
| Optional AI agent | Groq for separate `/v1/guidance` only | not used to create the grounded troubleshooting plan |
| Frontend | Vanilla HTML/CSS/JS, no framework, no build step | zero install friction for a demo; mobile-first responsive CSS |
| Testing | `unittest`, benchmark, supplied-input evaluator | schema, grounding, catalog integrity, cache behavior, latency, supplied-query review |

No database, no queue, no container orchestration — not justified at this
scale and not requested by the spec.

---

## 5. USP — what's actually different here

Every team got the same `deeplinks.json`, the same 20 SIIS entries, the
same schema. Describing "a RAG pipeline that maps complaints to deeplinks"
isn't a differentiator — it's the assignment. What we think actually holds
up under judge questioning:

1. **Grounding is checked in code.** Steps are segmented from SIIS text and
   verified as source excerpts. Deeplinks must be exact catalog entries;
   the catalog's dummy placeholder is excluded.
2. **A wrong deeplink is worse than no deeplink, and the code reflects that
   priority.** The classifier defaults to `manual` (no deeplink) whenever
   there's no clear settings/software cue in the text, specifically to avoid
   confidently pointing someone at the wrong screen. Most quick
   implementations optimize for coverage (more matches = flashier demo); we
   optimized for not being wrong, and can show the reasoning.
3. **Probe before a long checklist.** Ambiguous queries can return one
   source-authored observation first. See `docs/differentiator-research.md`
   and the query-by-query results in `docs/input-evaluation.md`.
4. **No LLM call in the plan path.** The core endpoint is deterministic
   and works without a model credential. Groq remains optional for the
   separate `/v1/guidance` route.
5. **Named, fixed bugs with before/after evidence**, not just a clean final
   state — e.g. a keyword-matching bug where `"wipe"` matched inside
   `"Swipe"` and misclassified a normal gesture as a factory reset; a
   false-positive deeplink match traced to generic shared vocabulary
   outranking a specific one; a cache bug where pre-warming silently never
   wrote to the cache. All in `docs/implementation-plan.md` with the actual
   fix.

We can't promise judges will agree these matter most — that's genuinely
outside anyone's control. What we can promise is that every claim above is
backed by a command you can run in front of them.

## 7. Industry pattern and differentiator

ServiceNow documents a troubleshooting agent that gathers case context,
finds missing context from related cases and knowledge, then proposes
additional steps. Microsoft Dynamics documents intent-based questions and
case next-best-actions. This project's narrower distinction is selecting a
safe, already-authored SIIS check when a complaint is underspecified or
retrieved procedures compete, then
verifying the returned step and any deeplink against the supplied assets.
Research sources and limitations are in
[`docs/differentiator-research.md`](docs/differentiator-research.md).

---

## 8. Layout

```
app/
  main.py                FastAPI app: POST /v1/troubleshoot, GET /health, CORS
  pipeline.py             orchestrates every stage below
  query_enrichment.py      Stage 0 — canonicalize + retain entities
  retrieval.py              SIIS BM25/topic retrieval and relevance gates
  extraction.py            Stage 1 — SIIS text -> Goal/Action/StepGroup
  grounding.py              source-excerpt and catalog integrity checks
  diagnostics.py            adaptive source-grounded probe selection
  deeplink_matcher.py       catalog BM25 + local TF-IDF retrieval
  response_builder.py       assembles and validates the final schema.Goal
  cache.py                  exact canonical fast-path cache
  llm_enhancer.py           optional Groq `/v1/guidance` layer
  schema.py                official Pydantic contract (unmodified)
frontend/
  index.html / style.css / app.js    optional mobile-first demo client
tests/
  run_benchmark.py          offline schema/cache/latency benchmark
  test_engine.py            grounding, retrieval, cache, safety regressions
  evaluate_inputs.py        all supplied complaints with evidence
data/                      the supplied kit files, copied in as-is
docs/                      specification, audit, evaluation and research notes
.env.example               copy to .env for the optional Groq key
requirements.txt
```
