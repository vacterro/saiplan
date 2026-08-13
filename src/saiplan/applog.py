"""Rotating crash/debug log under logs/ (separate from semantic LOG.md).

Spec 18: `logs/` holds app debug/crash output; PLAN LOG.md holds semantic
history. A crash never takes the app down silently — the unhandled-exception
hook writes a full traceback to both `logs/crash.log` and the rotating log.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("saiplan")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger  # already configured

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "saiplan.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    def _excepthook(exc_type, exc_value, exc_tb):
        body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("unhandled exception:\n%s", body)
        try:
            with open(log_dir / "crash.log", "a", encoding="utf-8") as fh:
                fh.write(f"\n--- {__import__('datetime').datetime.now()} ---\n{body}")
        except OSError:
            pass

    sys.excepthook = _excepthook
    return logger
