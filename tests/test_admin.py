"""Guards on the destructive admin commands.

Stateless: no database, no network. The delete queries themselves need a live
Postgres and are exercised by running scripts/reset_responses.py; what is worth
pinning here is the refusal to touch anything but the dev database.
"""

from __future__ import annotations

import pytest

from app.admin import ensure_local
from app.config import ENV_LOCAL, ENV_PROD


def test_ensure_local_allows_the_dev_database():
    ensure_local(ENV_LOCAL)


def test_ensure_local_refuses_prod():
    with pytest.raises(SystemExit) as excinfo:
        ensure_local(ENV_PROD)
    assert ENV_PROD in str(excinfo.value)


@pytest.mark.parametrize("app_env", ["", "PROD", "Local", "staging", "prod "])
def test_ensure_local_refuses_anything_it_does_not_recognise(app_env):
    """Only an exact 'local' passes.

    load_settings lowercases and strips APP_ENV, but this must not quietly
    accept a near miss if it is ever called from somewhere that does not.
    """
    with pytest.raises(SystemExit):
        ensure_local(app_env)
