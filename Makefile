.PHONY: install playground run

install:
	uv sync

playground:
	uv run adk web . --host 127.0.0.1 --port 8080

run:
	uv run uvicorn expense_agent.fast_api_app:app --host 127.0.0.1 --port 8080 --env-file .env

generate-traces:
	uv run python tests/eval/generate_traces.py

grade:
	uv run --env-file .env agents-cli eval grade --traces artifacts/traces/generated_traces.json --config tests/eval/eval_config.yaml
