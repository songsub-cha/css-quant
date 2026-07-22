"""Test-collection env scaffolding.

``Settings.cookie_secure`` (SoT D2) has no default on purpose — every
deployment must set it explicitly. But two modules build a module-level
``Settings()`` at *import* time: ``src/workers/settings.py`` (imported by
``tests/test_worker_settings.py``) and ``alembic/env.py``. Without
``COOKIE_SECURE`` present in the environment before those imports happen,
pytest collection itself fails with a ``ValidationError`` before any test
runs.

pytest imports ``conftest.py`` ahead of collecting test modules in the same
directory tree, so setting the env var here (rather than in a fixture, which
would run too late) is what makes collection succeed. This is test-process
scaffolding only — real deployments must still set ``COOKIE_SECURE``
explicitly via ``.env`` (dev/prod compose ``env_file``); nothing here
weakens that requirement.
"""

import os

os.environ.setdefault("COOKIE_SECURE", "false")
