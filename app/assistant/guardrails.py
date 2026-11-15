"""Input guardrail: masks personal details in the claim before any model or trace sees it.

The P3 golden set showed the LLM repeating card and phone numbers from the claim (4 of 60 replies), and
prompt rules didn't stop it reliably. A model can't leak what it never received, so this runs in code.
Regex-based for now; P6 replaces it with Microsoft Presidio (names, addresses, more formats) and adds
output checks.
"""

import re

# Order matters: full card numbers before shorter digit patterns.
PATTERNS = [
    ("card_number", re.compile(r"\b\d(?:[ -]?\d){12,18}\b"), "[card number]"),
    ("security_code", re.compile(r"\b(cvv|cvc|security code)(\W{0,3})\d{3,4}\b", re.IGNORECASE), r"\1\2[hidden]"),
    ("sin", re.compile(r"\b(sin)(\W{0,3})\d{3}[ -]?\d{3}[ -]?\d{3}\b", re.IGNORECASE), r"\1\2[hidden]"),
    ("account_number", re.compile(r"\b(account)(\W{0,3})\d{6,}\b", re.IGNORECASE), r"\1\2[hidden]"),
    ("phone", re.compile(r"\b\d{3}[ .-]\d{3}[ .-]\d{4}\b"), "[phone]"),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[email]"),
    ("card_last4", re.compile(r"\b(ending(?: in)?) \d{4}\b", re.IGNORECASE), r"\1 [hidden]"),
]


def mask_pii(text):
    """Returns (masked text, {kind: count})."""
    found = {}
    for kind, pattern, replacement in PATTERNS:
        text, n = pattern.subn(replacement, text)
        if n:
            found[kind] = n
    return text, found
