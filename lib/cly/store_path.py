"""Resolve native store after cly has applied a profile's environment."""
import sys
import sessions

print(sessions.root(sys.argv[1]) if sys.argv[1] in sessions.KINDS else "")
