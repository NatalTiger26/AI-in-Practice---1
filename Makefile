.PHONY: help venv setup setup-full check ratecheck offline data primer tickets test lint cost docs clean

# ---------------------------------------------------------------------------
# All Python execution goes through `uv run`, which:
#   - discovers .venv/ automatically (no "forgot to activate" failure)
#   - does not care if the repo path contains spaces
#   - stays consistent with `uv pip install`
#
# The only place we point at a concrete interpreter is `uv pip install`,
# which needs to know which venv to target when nothing is activated.
# ---------------------------------------------------------------------------
VENV   := .venv
# macOS / Linux interpreter path
PYBIN  := $(VENV)/bin/python
# Windows interpreter path (unused on Mac, kept for parity)
PYBINW := $(VENV)/Scripts/python.exe

help:
	@echo "make setup       create .venv and install what Labs 1-2 need (~290 MB, fast)"
	@echo "make setup-full  add the retrieval stack -- needed from Lab 3 (~1.8 GB)"
	@echo "make env         create .env from the template (does not overwrite)"
	@echo "make check       verify the environment and make one live model call"
	@echo "make ratecheck   measure your key's rate-limit headroom (~40 calls)"
	@echo "make offline     run the check in offline replay mode (costs nothing)"
	@echo "make data        regenerate the ticket dataset (deterministic)"
	@echo "make primer      Lab 1 Pydantic primer -- no API key, no cost"
	@echo "make tickets     print five random tickets with their gold labels"
	@echo "make test        run the unit tests"
	@echo "make lint        ruff"
	@echo "make cost        show what you have spent and what is cached"
	@echo "make docs        rebuild the syllabus, proposal, decks, and the aip reference"
	@echo "make clean       remove caches, traces, and the vector index"
	@echo ""
	@echo "requires: uv  (https://docs.astral.sh/uv/)"

# ---------------------------------------------------------------------------
# Ensure uv is installed. Every target that shells out to uv depends on this.
# ---------------------------------------------------------------------------
.uv-check:
	@command -v uv >/dev/null 2>&1 || { \
	  echo "uv is not installed."; \
	  echo "Install it with:  curl -LsSf https://astral.sh/uv/install.sh | sh"; \
	  echo "or:               brew install uv"; \
	  exit 1; }

# ---------------------------------------------------------------------------
# venv: `uv venv` is a no-op if .venv already exists, so this is safe to
# call unconditionally. It will not clobber an existing environment.
# ---------------------------------------------------------------------------
venv: .uv-check
	@if [ -d "$(VENV)" ]; then \
	  echo "$(VENV) already exists -- leaving it alone"; \
	else \
	  echo "creating $(VENV) with uv..."; \
	  uv venv "$(VENV)"; \
	fi

# Two tiers, deliberately. The full dependency set is ~1.8 GB and almost all
# of it is PyTorch, pulled in by sentence-transformers for Lab 3's local
# embeddings and reranker. Nothing before Lab 3 imports it -- the heavy imports
# in aip/ are lazy -- so making every student download it to run Lab 1 costs
# them fifteen minutes and buys nothing.
setup: venv
	@$(MAKE) --no-print-directory _install REQS=requirements-lab1.txt TIER="Labs 1-2"

setup-full: venv
	@$(MAKE) --no-print-directory _install REQS=requirements.txt TIER="all labs"

_install: .uv-check
	uv pip install --python "$(PYBIN)" -r $(REQS)
	@echo ""
	@echo "Installed $(TIER) dependencies into $(VENV)"
	@echo "Next: run 'make env', add your API key to .env, then 'make check'"
	@echo "You do NOT need to activate the venv for make targets -- uv run finds it."

# `.env.example` starts with a dot, so Finder and Explorer hide it by default.
env:
	@if [ -f .env ]; then \
	  echo ".env already exists -- not touching it."; \
	  echo "Edit it and put your key after GEMINI_API_KEY="; \
	else \
	  cp .env.example .env; \
	  echo "Created .env from the template."; \
	  echo ""; \
	  echo "Now open .env in any editor and put your key after GEMINI_API_KEY="; \
	  echo "Get a free one at https://aistudio.google.com/apikey"; \
	  echo "Then run: make check"; \
	fi

check: .uv-check
	@uv run python -c "import litellm" 2>/dev/null || { \
	  echo "Dependencies are not installed in $(VENV)."; \
	  echo "Run:  make setup"; exit 1; }
	uv run python scripts/check_setup.py

ratecheck: .uv-check
	uv run python scripts/check_rate_limit.py

offline: .uv-check
	AIP_OFFLINE=1 uv run python scripts/check_setup.py

data: .uv-check
	uv run python scripts/make_tickets.py

primer: .uv-check
	uv run python labs/lab1/pydantic_primer.py

tickets: .uv-check
	@uv run python -c "import json,random; \
	rows=[json.loads(l) for l in open('data/eval/extraction_dev.jsonl')]; \
	[print('='*70,'\n',r['expected'],'\n','-'*70,'\n',r['input'],sep='') \
	 for r in random.sample(rows,5)]"

test: .uv-check
	uv run python -m pytest tests/ -q

lint: .uv-check
	uv run python -m ruff check aip/ labs/ scripts/ tests/

cost: .uv-check
	@uv run python -c "from aip import cache; from aip.cost import global_budget; \
	print('cached:', cache.stats()); print(global_budget().report())"

docs: .uv-check
	uv pip install --python "$(PYBIN)" python-docx python-pptx markdown
	uv run python scripts/build_syllabus_docx.py
	uv run python scripts/build_proposal_html.py
	uv run python scripts/build_decks.py
	uv run python scripts/build_html_decks.py
	uv run python scripts/build_aip_docs.py

clean:
	rm -rf .aip_traces .chroma .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
	@echo "kept .aip_cache -- delete it by hand if you really mean to re-pay"