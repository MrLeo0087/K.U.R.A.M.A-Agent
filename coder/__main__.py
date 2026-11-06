"""`python -m coder …`: the coding agent from a terminal (see coder/interfaces/cli.py)."""
import sys

from coder.interfaces.cli import main

sys.exit(main())
