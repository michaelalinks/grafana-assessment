PYTHON ?= python3
GIT_URL ?= https://github.com/michaelalinks/grafana-assessment.git
REF ?= main

.PHONY: deploy forward test render clean

deploy:
	$(PYTHON) bootstrap.py --git-url "$(GIT_URL)" --ref "$(REF)"

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
	kubectl -n flux-system delete kustomization assessment-portable --wait=true
	kubectl -n flux-system delete gitrepository assessment-portable --ignore-not-found
