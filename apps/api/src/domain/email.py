"""Email sender port (SoT B2 — domain, ADR 0004/B3 fake-by-default).

Lives here — not alongside ``FakeEmailSender`` in ``src/adapters/email.py``
— for the same reason ``UserRepository`` (src/domain/user.py) does:
``src.api.v1`` needs the ``EmailSender`` type for a ``Depends(...)``
annotation on the password-reset request route, but the import-linter
contract forbids ``src.api.v1`` from importing ``src.adapters`` directly.
A real SMTP-backed implementation is a later issue's scope, added behind
this same Protocol the way ``OpenAILLMClient`` will sit behind ``LLMClient``.
"""

from __future__ import annotations

from typing import Protocol


class EmailSender(Protocol):
    """Port for outbound email, selected the same way ``LLMClient`` is (SoT B3)."""

    async def send(self, *, to: str, subject: str, body: str) -> None: ...
