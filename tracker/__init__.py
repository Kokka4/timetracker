"""Local-only desktop + browser time tracker.

Nothing in this package makes an outbound network request. The HTTP server
binds to the loopback interface only and the SQLite database never leaves
the machine it was written on.
"""

__version__ = "1.0.0"
