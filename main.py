"""Frozen entry point for Nuitka.

Compiling `src/saiplan/main.py` directly makes it the `__main__` module,
where its relative imports (`from .applog import ...`) have no parent
package. This shim keeps the frozen entry a thin absolute import, so the
whole package loads normally. Source runs keep using `python -m saiplan.main`
or the `saiplan` console script.
"""

from saiplan.main import main

if __name__ == "__main__":
    raise SystemExit(main())
