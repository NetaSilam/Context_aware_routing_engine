Overview
This is a full-stack web application for geospatial accident intelligence and historical road-risk analysis in Israel.

The project is a portfolio project demonstrating backend APIs, geospatial processing, industry-standard data pipelines, EDA, ETL, data quality checks, and dashboards.

Stack
Backend: FastAPI
Database: PostgreSQL + PostGIS
Frontend: React + Leaflet

for general project info read README.md. See [`PROJECT_REQUIREMENTS.md`](PROJECT_REQUIREMENTS.md) for the full spec, architecture, and TODO list.

for information regarding the data, read data/README.md.


# Engineering Principles

- Prefer explicit code over clever abstractions
- Keep modules cohesive
- Avoid premature optimization
- Prefer simple APIs
- Keep ownership boundaries clear
- Hide complexity behind stable interfaces
- Use meaningful and easy to understand naming convention. good example: traffic_coverage_service. bad example: todo3_traffic_coverage.

# Communication Style Rules

- Be concise. Skip preamble, affirmations, and summaries unless asked.
- Use simple and direct engineering language. do not assume i am familiar with intermediate concepts.
- Avoid abstract terminology unless immediately defined with a concrete example
- when naming any code piece, use a clear name that represents the functionality.
- Prefer concrete code-level explanations over conceptual explanations
- Prefer concrete code-level explanations
- Explain runtime behavior and data flow
- Show exact files/functions/modules
- Use examples from the current codebase
- Speak like an experienced engineer mentoring a junior developer
- Optimize for clarity, not sophistication
