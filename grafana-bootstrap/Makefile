PYTHON ?= python3

.PHONY: deploy forward test render clean

deploy:
	$(PYTHON) bootstrap.py deploy

forward:
	kubectl -n monitoring port-forward --address=127.0.0.1 service/grafana 3000:3000

.venv/bin/python: tests/requirements.txt
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -r tests/requirements.txt

test: .venv/bin/python
	.venv/bin/python -m pytest tests/ -v

render:
	kubectl kustomize .

clean:
	$(PYTHON) bootstrap.py clean
