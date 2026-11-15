.PHONY: demo test generator-ui

test:
	cd backend && .venv/bin/pytest -q
	PYTHONPATH=. backend/.venv/bin/pytest generator/tests -q

generator-ui:
	PYTHONPATH=. backend/.venv/bin/python -m generator serve --host 127.0.0.1 --port 8100

demo:
	@test -f .env || (echo "Скопіюй .env.example у .env (demo-логіни вже задані)." && exit 1)
	set -a && . ./.env && set +a; \
	( cd backend && .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 ) & \
	( cd vita-astronaut-health-monitor/frontend && npm run dev -- --port 3000 ) & \
	( PYTHONPATH=. backend/.venv/bin/python -m generator serve --host 127.0.0.1 --port 8100 ) & \
	sleep 3; \
	PYTHONPATH=. backend/.venv/bin/python -m generator run --plan multi_astronaut --time-scale 60 --backend http://127.0.0.1:8000 --device-token "$$DEVICE_TOKEN"
