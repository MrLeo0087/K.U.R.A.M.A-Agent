"""python -m jarvis.workers [--only a,b] [--list]"""
import sys

from jarvis.core.privacy import harden

harden()  # before anything creates files under data/

from jarvis.workers.supervisor import main  # noqa: E402

sys.exit(main())
