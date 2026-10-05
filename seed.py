"""First-run seeding for the persistent volume."""

import logging
from pathlib import Path

from config import runtime_paths
from storage import atomic_write

logger = logging.getLogger(__name__)

_BUNDLED_DESIGN = Path(__file__).parent / "DESIGN.md"


def ensure_design_file() -> None:
    """Copy the bundled reference design.md onto the volume if none exists."""
    dest = Path(runtime_paths()["design_file"])
    if dest.exists():
        return
    try:
        if _BUNDLED_DESIGN.exists():
            # Atomic, so a failed copy leaves no partial file that would stop
            # the next startup from seeding again.
            atomic_write(dest, _BUNDLED_DESIGN.read_bytes())
            logger.info("Seeded default design file at %s", dest)
    except OSError as e:
        logger.warning("Could not seed design file at %s: %s", dest, e)
