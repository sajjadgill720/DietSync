# DietSync Skills — Quick Reference

Use this to find the right skill for your task.

| I'm working on... | Load this skill |
|:---|:---|
| LangGraph nodes, graph topology, adding a new check type | `langgraph-workflow` |
| DRAP, RxNorm, openFDA, brand resolution, `resolve_drug()` | `drug-resolution-pipeline` |
| Database tables, ORM models, Alembic migrations, indexes | `database-schema` |
| Running tests, seeding data, evaluation benchmarks, demo pairs | `testing-and-eval` |

## Skill Dependencies

Some skills reference concepts from others. If you're loading one, you may also need the other:

- `langgraph-workflow` → references tables from `database-schema` (e.g. `fda_labels`, `drug_ingredients`)
- `drug-resolution-pipeline` → populates tables described in `database-schema`
- `testing-and-eval` → seeds data described in `database-schema`, runs graphs from `langgraph-workflow`
