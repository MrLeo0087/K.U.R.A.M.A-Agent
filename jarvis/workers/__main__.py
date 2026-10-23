"""python -m jarvis.workers [--only a,b] [--list]"""
import sys

from jarvis.workers.supervisor import main

sys.exit(main())
