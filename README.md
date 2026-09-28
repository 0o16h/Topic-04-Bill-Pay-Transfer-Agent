# Bill Pay & Transfer Agent (Track 04) — Iraqi Arabic

An agent that turns a sentence in Iraqi dialect ("حول 20 الف لاحمد كريم", "ادفع الكهرباء 15 الف") into a **confirmed** transaction against a mock wallet. Nothing executes without an explicit confirmation from the user.

## How it works

1. `main.py` — chat loop + tool-calling agent (Groq). Up to 5 tool rounds per message.
2. `confirmation_layer.py` — two-step flow: `prepare_*` (validates, executes nothing, returns a readable confirmation with the balance after) then `confirm_pending_action` (the only path to execution).
3. `mock_wallet.py` — mock wallet: contacts (incl. two "احمد"), billers, balance, history.

The real `transfer_money` / `pay_bill` are **not** exposed to the model as tools, so it cannot skip confirmation.

## Requirements coverage

| Brief requirement | How |
|---|---|
| Explicit confirmation | prepare → confirm; confirming in the same turn it was prepared is rejected by code |
| Ask, don't guess | ambiguous contact returns the candidates; the agent asks |
| Retries never double-pay | each `pending_id` executes once; repeat confirm returns the original result; identical pending requests reuse the same id; lock for concurrent calls; warning when an identical payment was made in the last 5 min |
| Honest failure messages | insufficient balance, unknown contact/biller, invalid amount, expired confirmation |

## Documented failure modes

| # | Failure | Handling |
|---|---|---|
| 1 | User/network/model repeats the confirmation | idempotent execution by `pending_id` (see above) |
| 2 | Model invents tool arguments (e.g. `bill_type: electricity`) | enum on biller names; the error goes back to the model so it retries; max 5 rounds |
| 3 | Model tries to prepare and confirm in the same turn | turn gate in code: confirmation needs a later user message |
| 4 | Ambiguous name ("احمد") | agent must list full names and ask; never picks one |
| 5 | LLM provider deprecates the model (404) | model name comes from `.env`; switched to `openai/gpt-oss-120b` |

## Evaluation

50 cases in `test_cases.json` (11 categories: dialect transfers/bills, ambiguous contact, unknown target, insufficient funds, missing info, malformed, two-in-one, cancel/change, queries, prompt-injection). Cases were drafted with Claude and reviewed/edited by hand. We score **wallet state**, not model text.

```bash
python run_eval.py --selfcheck   # validates the test file, no LLM
python run_eval.py               # runs everything, writes eval_report.md/json
```

**Results:**

| Metric | Result |
|---|---|
| Overall pass | 48/50 (96%) |
| Safety (no execution before confirmation) | 50/50 (100%) |
| Intent/extraction (correct pending after msg 1) | 43/45 (96%) |
| Final wallet state correct | 48/50 (96%) |
| Should-not-go-through correctly blocked | 24/24 (100%) |
| API errors | 0 |

**Known failing cases and why:**
- T06 — contact typed with hamza ("أحمد جبار") doesn't match the stored name without hamza ("احمد جبار"); simple string match, no Arabic spelling normalization.
- T15 — colloquial phrase "اشحن هاتفي" (charge my phone) not reliably mapped by the model to the "زين" biller; relies on LLM interpretation rather than a hard rule.

## Disclosure

- LLM at runtime: Groq API, `openai/gpt-oss-120b` (started with `llama-3.3-70b-versatile`, which Groq retired on 16 Aug 2026).
- Libraries: groq, python-dotenv, arabic-reshaper, python-bidi.
- AI coding assistant: Claude (Anthropic) helped write the code and draft the test cases; all code was run and checked by the team.
- Data: fully synthetic and hand-written mock wallet; no real customer data.

## User evidence

_2–3 lines: who you spoke to (e.g. a ZainCash user), what confused them in the normal flow, what they said about the agent._

## Run

```bash
python -m venv .venv && .venv\Scripts\Activate.ps1
pip install groq python-dotenv arabic-reshaper python-bidi
# .env: GROQ_API_KEY=...   GROQ_MODEL=openai/gpt-oss-120b
python main.py
```
