"""Password reset orchestration (SoT B2 — services layer, A5.1).

Two flows: ``request_password_reset`` issues a token for an existing email
without ever revealing whether the email is registered (account enumeration
— same principle as ``services.auth.login`` collapsing "unknown email" and
"wrong password" into one response), and ``confirm_password_reset`` consumes
a token exactly once to replace the password hash.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.domain.email import EmailSender
from src.domain.password_reset import (
    PasswordResetTokenRepository,
    generate_reset_token,
    hash_reset_token,
)
from src.domain.security import hash_password
from src.domain.user import UserRepository
from src.errors import ApiError, ErrorCode

RESET_TOKEN_TTL = timedelta(minutes=30)

_RESET_EMAIL_SUBJECT = "QuantPilot password reset"
_INVALID_RESET_TOKEN_DETAIL = "This password reset link is invalid or has expired."


async def request_password_reset(
    user_repo: UserRepository,
    token_repo: PasswordResetTokenRepository,
    email_sender: EmailSender,
    *,
    email: str,
) -> None:
    user = await user_repo.get_by_email(email)
    if user is None:
        # No token issued, no email sent, no error raised — a caller can't
        # tell an unregistered email apart from one that just got a reset
        # link (SoT A5.1: "항상 200을 반환").
        return

    token = generate_reset_token()
    now = datetime.now(UTC)
    await token_repo.create(
        user_id=user.id,
        token_hash=hash_reset_token(token),
        expires_at=now + RESET_TOKEN_TTL,
    )
    await email_sender.send(
        to=user.email,
        subject=_RESET_EMAIL_SUBJECT,
        body=f"Use this token to reset your password: {token}",
    )


async def confirm_password_reset(
    user_repo: UserRepository,
    token_repo: PasswordResetTokenRepository,
    *,
    token: str,
    new_password: str,
) -> None:
    user_id = await token_repo.use_token(hash_reset_token(token), now=datetime.now(UTC))
    if user_id is None:
        # Expired, already used, and never-existed all collapse to the same
        # error — distinguishing them would let a caller probe token
        # validity (SoT A5.1: "구체적 사유는 노출하지 않는다").
        raise ApiError(
            status=400, code=ErrorCode.INVALID_RESET_TOKEN, detail=_INVALID_RESET_TOKEN_DETAIL
        )

    await user_repo.update_password_hash(user_id, hash_password(new_password))
