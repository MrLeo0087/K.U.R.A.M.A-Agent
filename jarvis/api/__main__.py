import sys

from jarvis.core.privacy import harden

harden()  # data/ files private to this user
from jarvis.api.app import main  # noqa: E402

sys.exit(main())
