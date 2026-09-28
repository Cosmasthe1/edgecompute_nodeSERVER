Ship features together with their tests, in small focused commits high
Value scales with how much of the history can be mined into self-contained engineering tasks, changes that arrive with the tests proving them. Large mixed commits and test-less changes don't count toward that.
    Keep each feature or fix in its own commit (or small PR) that includes the tests pinning the new behavior.
    Avoid bulk commits that mix formatting, refactors, and features; they hide the mineable work.
Keep developing this repository over time, in real increments high
Buyers read the commit history as the product: a project built in a short burst, or by a single author, is a thinner mine than one with sustained back-and-forth development. Nothing cosmetic fixes this; only continued real work does.
    Keep landing real changes in small commits over the coming weeks; a steady history outweighs a polished snapshot.
    If teammates contribute, have them commit under their own identity so the history shows more than one human author.
Make install, build, and test work from a fresh clone high
One of the biggest drivers of what buyers pay is whether the project builds and its test suite actually runs, today, on a machine that has never seen it. No runnable suite was detected; adding one changes this repository's value more than any other item on this list.
    Clone the repository into an empty directory and follow only the README: every missing step you hit is a step to add.
    Commit a lockfile for every package manager so installs are reproducible.
    Make the test command explicit in the README and CI, and ensure CI runs it on every push.
Commit a real lockfile and fix the lockfile gap CI already checks for medium
repo_stats.py reports lockfiles_found: [] even though README describes a pip-compile workflow and CI has a 'Check lockfiles are up-to-date' step against requirements.in; the committed requirements.txt is either missing or not recognized as pinned.
    Run pip-compile requirements.in -o requirements.txt and pip-compile requirements-dev.in -o requirements-dev.txt in the repo root to regenerate fully pinned lockfiles.
    Commit both requirements.txt and requirements-dev.txt with the pip-compile header intact so CI's pip-compile --check step passes.
    Verify with pip-compile --check --output-file=requirements.txt requirements.in exiting 0, matching the exact command already in .github/workflows/ci.yml.
Spread development over real calendar time with small tested commits high
git_stats shows all 37 commits landed by a single author in a 1-day span with zero tags, which the README itself flags as a limitation; buyers weight sustained, incremental history highly.
    Pick one deferred item from the README table, e.g. 'Add Redis-backed Store implementation alongside the in-memory one', and implement it as its own commit with a matching test in tests/test_state.py.
    Implement 'Replace NodeAgent._execute's simulated sleep with real Docker container execution' as a second, separate commit with a new test in tests/test_agent.py (currently absent from test_spec_sample).
    Land each subsequent feature (e.g. Prometheus metrics for JCT/utilization mentioned in README next steps) as its own commit that includes the feature plus its test, repeated over multiple sessions/days rather than one burst.
Actually build-test the Docker Compose setup that the README admits is unverified medium
README explicitly states 'the Docker/Compose setup ... has not been build-tested in this environment' and has_devcontainer is false; docker-build in CI only builds the orchestrator image, not the full compose stack.
    Run docker compose up --build locally against docker-compose.yml and orchestrator/Dockerfile, fixing any startup or healthcheck failures.
    Add a CI job or step in .github/workflows/ci.yml that runs docker compose up --build --abort-on-container-exit and asserts the simulator container exits 0 with a JCT/success-rate report printed.
    Remove the README caveat once verified, replacing it with the actual verified command output.
Add tests for agent/node_agent.py and simulator/simulate.py directly medium
test_spec_sample lists 8 test files (test_metrics, test_integration_simulation, test_scheduler, test_logging, test_reliability, test_state, test_main, test_ledger) but none dedicated to agent/node_agent.py's _execute or run_forever logic in isolation, or simulator/simulate.py's reporting functions.
    Create tests/test_agent.py with unit tests for NodeAgent.poll_once and NodeAgent._execute using httpx mocking (respx or monkeypatch) to avoid a live server.
    Create tests/test_simulate.py exercising submit_jobs and wait_and_report against a mocked httpx.Client to verify JCT calculation logic.
    Update pytest --cov=orchestrator --cov=agent --cov-report=term in CI to also include --cov=simulator and raise --cov-fail-under from 50 to 70.
Wrap Prometheus metric emission in typed error handling instead of a bare except-pass low
orchestrator/main.py's _handle_job_result silently swallows all exceptions around JOB_RUNTIME_SECONDS.observe() with a bare except Exception: pass, which hides real bugs in the metrics path.
    Edit orchestrator/main.py to catch a narrower exception type (or log.exception the failure) instead of the bare except Exception: pass around JOB_RUNTIME_SECONDS.observe(runtime_seconds).
    Add a regression test in tests/test_metrics.py asserting that a metrics observation failure is logged rather than silently discarded.