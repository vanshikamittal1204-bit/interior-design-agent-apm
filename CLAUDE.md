# Project Context

This project is an AI Interior Design Agent built for an APM assignment.

## Goal

Generate feasible living room design recommendations from a provided SQLite catalog.

## Scope

MVP supports:
- Living Room only
- Budget-aware planning
- Layout validation
- Evaluation harness

## Hard Constraints

- Use only products from the SQLite catalog
- Never hallucinate products
- Never exceed budget
- Exclude out-of-stock items
- Exclude items with missing critical data
- Validate room fit before recommendation
- Refuse structural, electrical, and plumbing requests

## Agent Workflow

Brief Parser
→ Constraint Extractor
→ Priority Generator
→ Catalog Search
→ Planner
→ Budget Check
→ Layout Check
→ Replanner
→ Output Generator

## Evaluation Requirements

Hard Gates:
- Budget Compliance
- Catalog Compliance
- Room Fit
- Out-of-Scope Refusal

Quality Metrics:
- Style Fit
- Constraint Satisfaction
- Design Quality
- Tool Usage
- Replanning Efficiency
- Transparency

## Tech Stack

- Python
- Streamlit
- SQLite
- Pandas
- Pydantic

## Coding Guidelines

- Use type hints
- Use docstrings
- Keep modules small
- Separate business logic from UI
- Log all tool calls
- Log replanning decisions
- Log execution metrics