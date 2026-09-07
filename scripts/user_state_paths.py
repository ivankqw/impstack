"""Resolve configured user-state paths."""

from __future__ import annotations

import pathlib


def resolve(value: str | pathlib.Path, home: pathlib.Path) -> pathlib.Path:
    home = home.resolve()
    configured = pathlib.Path(value)
    relative = not configured.is_absolute()
    if configured.parts and configured.parts[0] == "~":
        path = home.joinpath(*configured.parts[1:])
    else:
        path = configured.expanduser()
    if not path.is_absolute():
        path = home / path
    resolved = path.resolve()
    if relative and not resolved.is_relative_to(home):
        raise ValueError("relative user-state path escapes home")
    return resolved
