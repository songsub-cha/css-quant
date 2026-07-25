"""Fake-by-default email adapter (SoT B3, ADR 0004 pattern applied to email).

``FakeEmailSender`` implements ``src.domain.email.EmailSender`` structurally
— no network call, captures every send so tests can assert on it, the same
role ``FakeLLMClient`` (src/adapters/llm.py) plays for LLM calls. A real
SMTP-backed implementation (``SMTP_*`` env vars, SoT D2) is out of scope for
this issue — the same precedent ``FakeLLMClient``-only set in a prior issue,
with the real provider following behind the same Protocol later.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SentEmail:
    to: str
    subject: str
    body: str


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[SentEmail] = []

    async def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append(SentEmail(to=to, subject=subject, body=body))
