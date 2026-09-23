# Groq AI + User Experience Memory

## What was added

The original project already had an optional Groq integration, but it was limited
to query paraphrases and description polishing. It did **not** learn from user
outcomes.

This feature adds a small retrieval-augmented experience memory:

1. User submits a troubleshooting complaint.
2. The existing deterministic engine produces the grounded Samsung steps.
3. `/v1/guidance` sends those grounded steps plus similar historical user
   experiences to Groq.
4. The model produces a short explanation and follow-up question. It is not
   allowed to invent steps, settings, diagnoses, or deeplinks.
5. The user can mark an action/solution as `Worked` or `Didn't work` and add
   an optional note.
6. `/v1/feedback` stores that experience locally in
   `data/experience_memory.json`.
7. Future similar complaints retrieve those records and provide them to Groq.

This is **retrieval-based learning**, not fine-tuning the LLM. It is much easier
to demonstrate in a hackathon because the team can show the memory growing
live and then show a similar complaint receiving experience-aware guidance.

## Setup

Create `.env` from `.env.example` and add:

```text
GROQ_API_KEY=your_key_here
```

Optional:

```text
GROQ_MODEL=llama-3.1-8b-instant
```

Start the backend normally:

```powershell
uvicorn app.main:app --reload
```

Start the frontend:

```powershell
cd frontend
python -m http.server 5500
```

Open:

```text
http://localhost:5500
```

## New API endpoints

### `POST /v1/guidance`

Input:

```json
{
  "query": "my screen keeps going black",
  "response": {
    "contexts": []
  }
}
```

The `response` should be the already-grounded result returned by
`/v1/troubleshoot`.

### `POST /v1/feedback`

Example:

```json
{
  "query": "my screen keeps going black",
  "outcome": "solved",
  "action_name": "Display Settings",
  "note": "Changing the display setting fixed it."
}
```

Allowed outcomes are `solved` and `not_solved`.

## Important demo story

Do not say "the LLM retrains itself from every user." That would be inaccurate.

Say:

> "The system has an experience memory. It stores user outcomes and retrieves
> relevant past experiences for similar complaints. Groq then uses those
> experiences as context while staying grounded in Samsung's verified
> troubleshooting steps."

That is a concrete GenAI + feedback-learning architecture without claiming
model fine-tuning.
