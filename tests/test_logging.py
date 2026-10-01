"""Log routing: Railway tags every stderr line as an error, so INFO must go to
stdout and only WARNING and above to stderr.

Runs in a subprocess because pytest installs its own logging handlers, which
would turn logging.basicConfig() into a no-op here.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True
    )


def test_info_goes_to_stdout_and_warnings_to_stderr():
    out = _run(
        "import logging, main\n"
        "logging.getLogger('x').info('routine line')\n"
        "logging.getLogger('x').warning('real problem')\n"
    )
    assert "routine line" in out.stdout and "routine line" not in out.stderr
    assert "real problem" in out.stderr and "real problem" not in out.stdout


def test_uvicorn_startup_lines_go_to_stdout():
    # Configure logging the way uvicorn does before it imports the app.
    out = _run(
        "import logging, logging.config\n"
        "from uvicorn.config import LOGGING_CONFIG\n"
        "logging.config.dictConfig(LOGGING_CONFIG)\n"
        "import app\n"
        "logging.getLogger('uvicorn.error').info('Application startup complete.')\n"
        "logging.getLogger('uvicorn.error').error('Exception in ASGI application')\n"
    )
    assert "Application startup complete." in out.stdout
    assert "Application startup complete." not in out.stderr
    assert "Exception in ASGI application" in out.stderr
