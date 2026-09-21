# WebTest Agent generator

This package turns a human-approved WebTest Agent review plan into a deterministic,
runnable Java 21/TestNG Maven project. It performs no LLM calls and writes no
credentials: secret-looking values are converted to environment references before
any generated artifact is persisted.

```bash
cd webtest-agent
PYTHONPATH=generator python3 -m webtest_generator.cli generate \
  --plan generator/fixtures/approved-plan.json \
  --output-root generated \
  --project-name sample-api-tests
```

The Python test suite is dependency-free:

```bash
PYTHONPATH=generator python3 -m unittest discover -s generator/tests -v
```

