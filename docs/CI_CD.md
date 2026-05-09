# CI/CD

This repository currently uses backend-only continuous integration.

## Workflow

GitHub Actions workflow:

```text
.github/workflows/backend-ci.yml
```

It runs on:

- pushes to `main`
- pull requests

The workflow:

- checks out the repository
- sets up Python 3.12
- installs `backend/requirements.txt`
- validates all JSON files in `data/`
- runs the backend pytest suite

External provider keys are explicitly blank in CI:

```text
OPENAI_API_KEY=
TINYFISH_API_KEY=
SEALION_API_KEY=
EXA_API_KEY=
DATABASE_URL=
RUN_LIVE_OPENAI_TESTS=0
RUN_LIVE_TINYFISH_TESTS=0
RUN_POSTGRES_INTEGRATION_TESTS=0
```

This keeps tests deterministic. Tests that exercise OpenAI, Google Calendar, TinyFish, Exa, or SEA-LION behavior must mock those boundaries. Research tests should prove that the local corpus is used and that mocked live-search results remain represented alongside local corpus results.

## Local Equivalent

Run the same core checks locally:

```bash
backend/.venv/bin/python -m json.tool data/grants_singapore.json >/dev/null
backend/.venv/bin/python -m json.tool data/educational_resources.json >/dev/null
backend/.venv/bin/python -m json.tool data/condition_trajectories.json >/dev/null
backend/.venv/bin/python -m json.tool data/singapore_support_corpus.json >/dev/null
TINYFISH_API_KEY= SEALION_API_KEY= EXA_API_KEY= OPENAI_API_KEY= DATABASE_URL= backend/.venv/bin/python -m pytest backend/tests
```

## Test Conventions

- Route-level API behavior belongs in `backend/tests/test_api_contracts.py`.
- Transcript extraction/triage behavior belongs in `backend/tests/test_extraction_triage.py`.
- Corpus retrieval, source classification, and local-plus-live evidence merging belong in `backend/tests/test_research_corpus.py`.
- Learning context, model evaluations, and prompt candidate safety belong in `backend/tests/test_learning_harness.py`.
- Network calls should be mocked unless the test is explicitly marked as an external integration test.
- New data files must be valid JSON and covered by at least one test that asserts required metadata.

## Opt-In Live Integration Tests

Live tests live in:

```text
backend/tests/test_live_integrations.py
```

They are skipped by default. Run only the live OpenAI transcription smoke test with:

```bash
RUN_LIVE_OPENAI_TESTS=1 \
OPENAI_API_KEY=... \
LIVE_OPENAI_AUDIO_PATH=/absolute/path/to/speech.wav \
backend/.venv/bin/python -m pytest backend/tests/test_live_integrations.py -m integration
```

Run only the live TinyFish search smoke test with:

```bash
RUN_LIVE_TINYFISH_TESTS=1 \
TINYFISH_API_KEY=... \
backend/.venv/bin/python -m pytest backend/tests/test_live_integrations.py -m integration
```

Run the Postgres schema/store roundtrip with a disposable test database:

```bash
RUN_POSTGRES_INTEGRATION_TESTS=1 \
TEST_DATABASE_URL=postgresql://... \
backend/.venv/bin/python -m pytest backend/tests/test_live_integrations.py -m integration
```

Use `TEST_DATABASE_URL`, not production `DATABASE_URL`. The test applies the schema and writes unique graph rows.
