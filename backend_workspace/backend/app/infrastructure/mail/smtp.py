"""SMTP adapter for transactional-outbox notification delivery (DEC-07)."""

from __future__ import annotations

import smtplib
import uuid
from email.message import EmailMessage
from typing import Callable

from app.core.config import Settings


class MailDeliveryError(RuntimeError):
    """A recoverable error while attempting asynchronous mail delivery."""


class SmtpMailSender:
    """Send allow-listed outbox messages through the configured SMTP relay."""

    def __init__(
        self,
        settings: Settings,
        smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
    ) -> None:
        """Create a sender without connecting until a dispatcher owns an event lease."""
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._username = settings.smtp_username
        self._password = settings.smtp_password
        self._from = settings.smtp_from
        self._recipients = settings.smtp_to
        self._starttls = settings.smtp_starttls
        self._timeout = settings.smtp_timeout_s
        self._smtp_factory = smtp_factory

    # PUBLIC_INTERFACE
    def send_asset_flagged(self, event_id: uuid.UUID, payload: dict[str, object]) -> None:
        """Deliver one asset-flagged email using ``event_id`` as its stable Message-ID.

        Raises:
            MailDeliveryError: SMTP is unconfigured or rejects the delivery.
        """
        if not self._host or not self._recipients:
            raise MailDeliveryError("SMTP_HOST and SMTP_TO must be configured for email delivery")
        try:
            message = self._build_asset_flagged_message(event_id, payload)
            with self._smtp_factory(self._host, self._port, timeout=self._timeout) as client:
                client.ehlo()
                if self._starttls:
                    client.starttls()
                    client.ehlo()
                if self._username:
                    client.login(self._username, self._password or "")
                client.send_message(message)
        except (OSError, smtplib.SMTPException, ValueError) as error:
            raise MailDeliveryError("SMTP delivery failed") from error

    def _build_asset_flagged_message(
        self,
        event_id: uuid.UUID,
        payload: dict[str, object],
    ) -> EmailMessage:
        """Build a plain-text message from the outbox's allow-listed alert fields."""
        asset_id = str(payload.get("assetId", "unknown"))
        score = str(payload.get("score", "unknown"))
        flagged_at = str(payload.get("flaggedAt", "unknown"))
        message = EmailMessage()
        message["From"] = self._from
        message["To"] = ", ".join(self._recipients)
        message["Subject"] = f"Asset {asset_id} requires maintenance"
        message["Message-ID"] = f"<{event_id}@asset-health-worker>"
        message.set_content(
            "An asset health score requires maintenance attention.\n\n"
            f"Asset ID: {asset_id}\n"
            f"Health score: {score}\n"
            f"Flagged at: {flagged_at}\n"
        )
        return message
