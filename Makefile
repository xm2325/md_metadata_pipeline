.PHONY: test lint demo clean schema build

test:
	pytest --cov=mdlit --cov-report=term-missing

lint:
	ruff check src tests real_study

schema:
	python -m mdlit.cli schema --output schemas/md_record.schema.json
	python -c "import json; from mdlit.models import ProtocolEvent; open('schemas/protocol_event.schema.json', 'w').write(json.dumps(ProtocolEvent.model_json_schema(), indent=2))"
	python -c "import json; from mdlit.annotation import AnnotationFact; open('schemas/annotation_fact.schema.json', 'w').write(json.dumps(AnnotationFact.model_json_schema(), indent=2))"

demo:
	python -m mdlit.cli extract \
		--xml data/demo/article.xml \
		--document-id PMC-SYNTHETIC-JR3997 \
		--source-uri synthetic://jr3997-regression-article \
		--output-dir artifacts/demo
	python -m mdlit.cli evaluate \
		--record artifacts/demo/record.json \
		--gold data/demo/gold.json \
		--output artifacts/demo/evaluation.json

clean:
	rm -rf artifacts .coverage htmlcov .pytest_cache

build:
	python -m build
