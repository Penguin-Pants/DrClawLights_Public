"""First-run seeding for the persistent volume."""

import logging
import shutil
from pathlib import Path

from config import runtime_paths

logger = logging.getLogger(__name__)

_BUNDLED_DESIGN = Path(__file__).parent / "DESIGN.md"


def ensure_design_file() -> None:
    """Copy the bundled reference design.md onto the volume if none exists."""
    dest = Path(runtime_paths()["design_file"])
    if dest.exists():
        return
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if _BUNDLED_DESIGN.exists():
            shutil.copyfile(_BUNDLED_DESIGN, dest)
            logger.info("Seeded default design file at %s", dest)
    except OSError as e:
        logger.warning("Could not seed design file at %s: %s", dest, e)
