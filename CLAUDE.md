# CLAUDE.md — supplier-price-monitoring-is

Educational information system: supplier material price monitoring (KPI, course "Інформаційні системи").
Spec-driven development. The file in /spec is the single source of truth.

## Layout
/spec — system concept, SRS (lab 2), open questions (Ukrainian)
/tests — pytest tests
/src — application code (Python 3.12, FastAPI, SQLite — to be confirmed in lab 2)
/docs — lab reports, diagrams (Ukrainian)
/logs — agent session log, gate decisions, conflict records (Ukrainian)

## Rules for the agent
- Code, comments, commit messages: English. /spec, /docs, /logs: Ukrainian.
- Do not commit. Stage changes and stop; the human reviews `git diff` and commits.
- Every change to /src needs a test in /tests.
- No new dependencies without a separate `chore:` commit.
- If a task conflicts with /spec — stop and report, do not resolve yourself.
- Commit format: `prefix: imperative summary` (<= 72 chars), prefixes spec:/test:/feat:/fix:/docs:/log:/gate:/chore:,
  trailer `Author-role: agent` + `Agent: claude-code`.
