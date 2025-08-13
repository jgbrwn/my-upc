# AGENTS.md

## Build/Lint/Test Commands
- Install dependencies: `poetry install`
- Run app: `poetry run python wsgi.py` or `poetry run flask run`
- Run tests: `poetry run python -m pytest tests/`
- Run single test: `poetry run python -m pytest tests/test_file.py::test_function_name`
- Lint: Use flake8 or pylint (not configured in project)

## Code Style Guidelines
- Use Flask for web framework
- Follow PEP 8 for Python code style
- Use SQLAlchemy for database operations
- Use pandas for data manipulation
- Use type hints where possible
- Use descriptive variable names (e.g., `upc_barcode`, `movie_data`)
- Handle errors with try/except blocks
- Use logging for debugging
- Use blueprints for route organization
- Use environment variables for secrets (OMDB_API_KEY)
- Use pagination for large result sets
- Validate and sanitize user inputs
- Use proper HTTP status codes
- Implement security measures (referrer checking)