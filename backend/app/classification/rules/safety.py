"""ReDoS safety verification for admin-supplied detector patterns.

Admin patterns run in worker processes over large document texts. Python's re
engine uses backtracking and cannot be interrupted mid-match, so potentially
catastrophic patterns must be rejected before saving.
"""

from __future__ import annotations

import re
import time
from typing import Final

MAX_PATTERN_LENGTH: Final[int] = 512
MAX_NESTING_DEPTH: Final[int] = 5
MAX_CANARY_SECONDS: Final[float] = 0.05

# Known dangerous structural patterns (nested quantifiers, overlapping branches)
_DANGEROUS_PATTERNS = (
    # Nested quantifiers like (a+)+, (a*)*, ([a-z]+)*, (a+){2,}, ([a-z]*)+
    re.compile(r"\([^)]*[\+\*][^)]*\)[\+\*]"),
    re.compile(r"\([^)]*\{[0-9]+,[0-9]*\}[^)]*\)[\+\*]"),
    re.compile(r"\([^)]*[\+\*][^)]*\)\{[0-9]+,[0-9]*\}"),
    # Identical alternations under repetition like (a|a)*
    re.compile(r"\(([^|)]+)\|\1\)[\+\*]"),
    # Repeated greedy dot captures like (.*a){10,}
    re.compile(r"\(\.\*[^)]*\)\{[1-9][0-9]+,\}"),
    re.compile(r"\(\.\*[^)]*\)\{[2-9][0-9]\}"),
)


class PatternUnsafeError(ValueError):
    """Raised when a regular expression pattern is unsafe or invalid."""


def assert_pattern_safe(pattern: str) -> None:
    """Verify that a regular expression is syntactically valid and safe from ReDoS.

    Raises:
        PatternUnsafeError: If the pattern is invalid, too complex, or prone to
            catastrophic backtracking.
    """
    if not pattern or len(pattern) > MAX_PATTERN_LENGTH:
        msg = f"pattern exceeds maximum length of {MAX_PATTERN_LENGTH} characters"
        raise PatternUnsafeError(msg)

    # 1. Syntax compilation check
    try:
        compiled = re.compile(pattern)
    except re.error as err:
        msg = f"invalid regular expression: {err}"
        raise PatternUnsafeError(msg) from err

    # 2. Structural inspection for nested quantifiers
    for dangerous in _DANGEROUS_PATTERNS:
        if dangerous.search(pattern):
            msg = "pattern contains potentially catastrophic nested quantifiers or alternations"
            raise PatternUnsafeError(msg)

    # Count parenthesis nesting depth
    depth = 0
    max_depth = 0
    escaped = False
    for char in pattern:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == "(":
            depth += 1
            max_depth = max(max_depth, depth)
        elif char == ")":
            depth = max(0, depth - 1)

    if max_depth > MAX_NESTING_DEPTH:
        msg = f"pattern exceeds maximum group nesting depth of {MAX_NESTING_DEPTH}"
        raise PatternUnsafeError(msg)

    # 3. Timing canary on pathological inputs
    canaries = [
        "a" * 35 + "!",
        "0" * 35 + "!",
        "A" * 35 + "!",
        " " * 35 + "!",
    ]
    for canary in canaries:
        start = time.perf_counter()
        try:
            compiled.search(canary)
        except Exception as err:
            msg = f"pattern execution failed on canary: {err}"
            raise PatternUnsafeError(msg) from err
        elapsed = time.perf_counter() - start
        if elapsed > MAX_CANARY_SECONDS:
            msg = f"pattern execution timed out ({elapsed:.3f}s > {MAX_CANARY_SECONDS}s)"
            raise PatternUnsafeError(msg)
