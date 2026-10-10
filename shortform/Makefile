# 간단 진입점. 설치는 전부 scripts/setup.sh (레포 안 .venv/·.tools/ 에만).
PY := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
# make 가 띄우는 명령에만 .tools 를 앞에 둔다 (셸 PATH 는 그대로)
export PATH := $(CURDIR)/.tools/bin:$(CURDIR)/.tools/node/bin:$(PATH)
export npm_config_cache := $(CURDIR)/.tools/npm-cache

.PHONY: setup setup-web setup-all doctor test build uninstall
setup:
	scripts/setup.sh --mode cli $(ARGS)
setup-web:
	scripts/setup.sh --mode web $(ARGS)
setup-all:
	scripts/setup.sh --mode all $(ARGS)
doctor:
	$(PY) -m shorts doctor $(ARGS)
test:
	node --test tests/unit/
	$(PY) -m unittest discover -s tests -p 'test_*.py'
build:
	npm run build
uninstall:
	scripts/setup.sh --uninstall $(ARGS)
