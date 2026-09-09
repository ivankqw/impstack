#!/usr/bin/env python3
"""PreToolUse(Bash) hook: advise review before a git push.

The match is command-position only. A bare substring also fires on prose
inside echo and grep arguments, and on paths like .../openai-codex/codex/1.0.4.
The match is textual, so it cannot see shell quoting: a command word inside a
quoted string still reads as command position. That is acceptable for an
advisory nudge.

Fails safe. Any unexpected input produces no output and a zero exit, because a
hook that raises turns a nudge into noise on every tool call.
"""
import json
import re
import sys

REVIEW = (
    "Review gate (advisory): this push ships work. Review it BEFORE the push.\n"
    "Use the selected reviewer profile, or the active preset reviewer when no factory plan is selected. Start it as a fresh "
    "independent context with no memory of this conversation. A mechanism that "
    "shares this session's context inherits the author's blind spots along with it.\n"
    "Do NOT tell it to skip what you already verified: a happy path checked by a "
    "test that mocks the broken thing is exactly where a shared blind spot hides."
)

CMD_POS = r"(?:^|[;&|]\s*|\$\(\s*|`\s*)"
GIT_PUSH = re.compile(CMD_POS + r"git\s+push\b")


def main() -> None:
    raw = sys.stdin.read()
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return

    tool_input = data.get("tool_input")
    command = (tool_input if isinstance(tool_input, dict) else {}).get("command", "")
    if not isinstance(command, str):
        return

    if GIT_PUSH.search(command):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": REVIEW,
            }
        }))


try:
    main()
except Exception:
    pass
sys.exit(0)
