import signal
import sys

from .cli import main

if hasattr(signal, "SIGPIPE"):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
sys.exit(main())
