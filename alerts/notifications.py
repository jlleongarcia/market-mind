"""
Email + Telegram delivery for alert digests.

Telegram is called through its plain HTTPS Bot API with urllib (no extra
dependency). Accounts are linked with a deep link (t.me/<bot>?start=<token>)
and confirmed by polling getUpdates — no webhook, so nothing new needs to be
reachable from the internet.
"""
import json
import logging
import urllib.error
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import AlertEvent, NotificationSettings

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE = 4096
# Undelivered events (e.g. SMTP was down) are retried on the next runs for this long
RETRY_WINDOW_DAYS = 3


class TelegramError(Exception):
    pass


def telegram_configured():
    return bool(getattr(settings, 'TELEGRAM_BOT_TOKEN', '') and getattr(settings, 'TELEGRAM_BOT_USERNAME', ''))


def telegram_request(method, payload=None, timeout=15):
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            description = json.loads(e.read().decode()).get('description', str(e))
        except Exception:
            description = str(e)
        raise TelegramError(description) from e
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise TelegramError(str(e)) from e
    if not body.get('ok'):
        raise TelegramError(body.get('description', 'unknown error'))
    return body.get('result')


def _chunks(text, size=TELEGRAM_MAX_MESSAGE):
    """Split on blank lines so an alert is never cut in half (unless it alone exceeds the limit)."""
    chunks, current = [], ''
    for block in text.split('\n\n'):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(block) > size:
            chunks.append(block[:size])
            block = block[size:]
        current = block
    if current:
        chunks.append(current)
    return chunks


def send_telegram(chat_id, text):
    for chunk in _chunks(text):
        telegram_request('sendMessage', {'chat_id': chat_id, 'text': chunk, 'disable_web_page_preview': True})


def telegram_link_url(token):
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={token}"


def find_telegram_chat_id(token):
    """
    Look through the bot's pending updates for "/start <token>" and return
    that chat's id. Updates are deliberately not acknowledged (no offset), so
    one user verifying never consumes another user's pending /start.
    """
    updates = telegram_request('getUpdates', {'allowed_updates': ['message']}) or []
    for update in reversed(updates):
        message = update.get('message') or {}
        if (message.get('text') or '').strip() == f"/start {token}":
            return str(message['chat']['id'])
    return None


def compose_digest(events, unevaluated):
    count = len(events)
    lines = [f"Market Mind — {count} alert{'s' if count != 1 else ''} for {timezone.now().date()}", '']
    for event in events:
        lines.append(event.message)
        lines.append('')
    if unevaluated:
        lines.append("Couldn't evaluate (missing data — not counted as matches):")
        for symbol, reason in sorted(unevaluated.items()):
            lines.append(f"  • {symbol}: {reason}")
        lines.append('')
    site = getattr(settings, 'SITE_URL', '').rstrip('/')
    if site:
        lines.append(f"Alert history: {site}/alerts/history/")
    lines.append('These are the conditions you set, not investment advice.')
    return '\n'.join(lines)


def send_digest(user, unevaluated):
    """
    Send every not-yet-delivered recent event for this user, one message per
    channel. Returns a short status string for the cron log.
    """
    prefs = NotificationSettings.for_user(user)
    since = timezone.now() - timedelta(days=RETRY_WINDOW_DAYS)
    recent = AlertEvent.objects.filter(user=user, created_at__gte=since).order_by('created_at')
    status = []

    if prefs.email_enabled and user.email:
        pending = list(recent.filter(emailed=False))
        if pending:
            try:
                send_mail(
                    subject=f"[Market Mind] {len(pending)} alert{'s' if len(pending) != 1 else ''}: "
                            f"{', '.join(sorted({e.symbol for e in pending}))}",
                    message=compose_digest(pending, unevaluated),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
                AlertEvent.objects.filter(id__in=[e.id for e in pending]).update(emailed=True)
                status.append(f"emailed {len(pending)}")
            except Exception as e:
                logger.error(f"Alert email to {user.username} failed: {e}")
                status.append('email failed')

    if prefs.telegram_enabled and prefs.telegram_chat_id and telegram_configured():
        pending = list(recent.filter(telegrammed=False))
        if pending:
            try:
                send_telegram(prefs.telegram_chat_id, compose_digest(pending, unevaluated))
                AlertEvent.objects.filter(id__in=[e.id for e in pending]).update(telegrammed=True)
                status.append(f"telegrammed {len(pending)}")
            except TelegramError as e:
                logger.error(f"Alert Telegram message to {user.username} failed: {e}")
                status.append('telegram failed')

    return ', '.join(status) or 'nothing to send'
