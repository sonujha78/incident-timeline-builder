"""Secret redaction. Applied to every string before it is stored or printed."""

import re

REDACTED = "[REDACTED]"

# (compiled pattern, replacement). Order matters: specific patterns first.
_PATTERNS = [
    # PEM private key blocks
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     REDACTED),
    # Authorization headers: Bearer / Basic tokens
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 " + REDACTED),
    # key=value / key: value / "key": "value" for sensitive key names
    (re.compile(
        r"""(?ix)
        (?P<k>["']?(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|
                     access[_-]?key|private[_-]?key|auth|credential[s]?)["']?
              \s*[:=]\s*)
        (?P<v>"[^"]*"|'[^']*'|[^\s,;&"']+)
        """),
     lambda m: m.group("k") + REDACTED),
    # Known token shapes
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), REDACTED),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), REDACTED),
    # JWT (three base64url parts)
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), REDACTED),
    # user:password@host in URLs
    (re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^/\s:@]+):(?P<pw>[^/\s@]+)@"),
     lambda m: f"{m.group('scheme')}{m.group('user')}:{REDACTED}@"),
]


def redact(text):
    """Return text with secrets replaced by [REDACTED]. Non-strings pass through."""
    if not isinstance(text, str):
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact_obj(obj):
    """Recursively redact strings inside dicts, lists and tuples."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj
