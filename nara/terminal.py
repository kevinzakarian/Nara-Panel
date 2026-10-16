"""Readable, optional ANSI styling for interactive command-line questions."""
import os
import sys


def styled(text, stream=None, color="36"):
    stream = stream or sys.stderr
    if stream.isatty() and os.environ.get("TERM", "dumb") != "dumb" and "NO_COLOR" not in os.environ:
        return "\033[1;" + color + "m" + text + "\033[0m"
    return text


def input_label(message, stream=None):
    return styled("  [INPUT] " + message, stream)
