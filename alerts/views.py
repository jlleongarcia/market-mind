"""
Frontend views: wishlist, alert rules (with a read-only "Test now" preview),
alert history and notification settings.
"""
import secrets
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .metrics import METRICS, build_snapshots, owned_symbols
from .models import AlertCondition, AlertEvent, AlertRule, NotificationSettings, WishlistItem
from .notifications import (
    TelegramError, find_telegram_chat_id, send_telegram, telegram_configured, telegram_link_url,
)
from .services import OPERATORS, preview_rule

PRESETS = {
    'yield_above_avg': {
        'name': 'Yield above its 5y average',
        'conditions': [('yield_vs_5y_avg', 'gt', Decimal('0'))],
    },
    'low_third_52w': {
        'name': 'Low third of its 52-week range',
        'conditions': [('week52_percentile', 'lte', Decimal('33'))],
    },
    'yield_and_low_third': {
        'name': 'Yield above 5y average AND low third of 52-week range',
        'conditions': [('yield_vs_5y_avg', 'gt', Decimal('0')), ('week52_percentile', 'lte', Decimal('33'))],
    },
}


# --------------------------------------------------------------------------- #
# Wishlist                                                                     #
# --------------------------------------------------------------------------- #

@login_required
def wishlist_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'delete':
            WishlistItem.objects.filter(id=request.POST.get('item_id'), user=request.user).delete()
            messages.success(request, 'Removed from your wishlist.')
            return redirect('alerts:wishlist_view')

        if action == 'note':
            item = get_object_or_404(WishlistItem, id=request.POST.get('item_id'), user=request.user)
            item.note = request.POST.get('note', '').strip()
            item.save(update_fields=['note'])
            messages.success(request, f'Note saved for {item.symbol}.')
            return redirect('alerts:wishlist_view')

        symbol = request.POST.get('symbol', '').strip().upper()
        note = request.POST.get('note', '').strip()
        if not symbol:
            messages.error(request, 'Enter a symbol.')
            return redirect('alerts:wishlist_view')
        if WishlistItem.objects.filter(user=request.user, symbol=symbol).exists():
            messages.info(request, f'{symbol} is already on your wishlist.')
            return redirect('alerts:wishlist_view')

        # Creates the Stock + metrics (incl. 5y price history) if we've never
        # seen it, so the daily cron jobs cover it from tomorrow on.
        from portfolio.services import PortfolioCalculationService
        ok, msg, stock = PortfolioCalculationService.ensure_stock_exists(symbol)
        if not ok:
            messages.error(request, msg)
            return redirect('alerts:wishlist_view')

        WishlistItem.objects.create(user=request.user, symbol=stock.symbol, note=note)
        messages.success(request, f'{stock.symbol} added to your wishlist.')
        return redirect('alerts:wishlist_view')

    items = list(WishlistItem.objects.filter(user=request.user))
    snapshots = build_snapshots(request.user, [i.symbol for i in items])
    rows = [{'item': i, 'snap': snapshots[i.symbol]} for i in items]
    return render(request, 'alerts/wishlist.html', {'rows': rows})


# --------------------------------------------------------------------------- #
# Rules                                                                        #
# --------------------------------------------------------------------------- #

def _parse_rule_form(post):
    """(fields, conditions, errors) from the rule editor's POST data."""
    errors = []
    fields = {
        'name': post.get('name', '').strip(),
        'scope': post.get('scope', 'BOTH'),
        'symbol': post.get('symbol', '').strip().upper(),
        'match': post.get('match', 'ALL'),
        'is_active': post.get('is_active') == 'on',
    }
    try:
        fields['cooldown_days'] = max(0, int(post.get('cooldown_days') or 7))
    except ValueError:
        fields['cooldown_days'] = 7
        errors.append('Cooldown must be a whole number of days.')

    if not fields['name']:
        errors.append('Give the rule a name.')
    if fields['scope'] not in dict(AlertRule.SCOPE_CHOICES):
        errors.append('Pick a valid scope.')
    if fields['scope'] == 'SYMBOL' and not fields['symbol']:
        errors.append('Enter the symbol this rule applies to.')
    if fields['scope'] != 'SYMBOL':
        fields['symbol'] = ''
    if fields['match'] not in dict(AlertRule.MATCH_CHOICES):
        errors.append('Pick ALL or ANY.')

    valid_metrics = {key for key, _, _ in METRICS}
    conditions = []
    for metric, op, raw in zip(post.getlist('metric'), post.getlist('operator'), post.getlist('value')):
        if not raw.strip():
            continue
        try:
            value = Decimal(raw.strip())
        except InvalidOperation:
            errors.append(f'"{raw}" is not a number.')
            continue
        if metric not in valid_metrics or op not in OPERATORS:
            errors.append('Invalid condition.')
            continue
        conditions.append((metric, op, value))
    if not conditions:
        errors.append('Add at least one condition.')
    return fields, conditions, errors


@login_required
def rules_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        rule = None
        if action in ('delete', 'toggle'):
            rule = get_object_or_404(AlertRule, id=request.POST.get('rule_id'), user=request.user)

        if action == 'delete':
            rule.delete()
            messages.success(request, f'Rule "{rule.name}" deleted.')
        elif action == 'toggle':
            rule.is_active = not rule.is_active
            rule.save(update_fields=['is_active', 'updated_at'])
            messages.success(request, f'Rule "{rule.name}" {"enabled" if rule.is_active else "paused"}.')
        elif action == 'preset' and request.POST.get('preset') in PRESETS:
            preset = PRESETS[request.POST['preset']]
            with transaction.atomic():
                rule = AlertRule.objects.create(user=request.user, name=preset['name'])
                for metric, op, value in preset['conditions']:
                    AlertCondition.objects.create(rule=rule, metric=metric, operator=op, value=value)
            messages.success(request, f'Rule "{rule.name}" created — tweak it below if you like.')
            return redirect('alerts:rule_edit_view', pk=rule.pk)
        return redirect('alerts:rules_view')

    rules = AlertRule.objects.filter(user=request.user).prefetch_related('conditions')
    return render(request, 'alerts/rules.html', {
        'rules': rules,
        'metric_labels': {key: label for key, label, _ in METRICS},
        'presets': PRESETS,
    })


@login_required
def rule_edit_view(request, pk=None):
    rule = get_object_or_404(AlertRule, pk=pk, user=request.user) if pk else None

    if request.method == 'POST':
        fields, conditions, errors = _parse_rule_form(request.POST)
        if not errors and fields['scope'] == 'SYMBOL':
            # Same as adding to the wishlist: make sure the daily metrics cron covers it
            from portfolio.services import PortfolioCalculationService
            ok, msg, stock = PortfolioCalculationService.ensure_stock_exists(fields['symbol'])
            if ok:
                fields['symbol'] = stock.symbol
            else:
                errors.append(msg)
        if errors:
            for e in errors:
                messages.error(request, e)
            form_conditions = [{'metric': m, 'operator': o, 'value': v} for m, o, v in conditions]
            return render(request, 'alerts/rule_form.html', _rule_form_context(rule, fields, form_conditions))

        with transaction.atomic():
            if rule is None:
                rule = AlertRule(user=request.user)
            for key, value in fields.items():
                setattr(rule, key, value)
            rule.save()
            rule.conditions.all().delete()
            for metric, op, value in conditions:
                AlertCondition.objects.create(rule=rule, metric=metric, operator=op, value=value)
            # Conditions changed, so yesterday's "currently matching" no
            # longer means anything — let every symbol be re-evaluated fresh.
            rule.states.all().delete()
        messages.success(request, f'Rule "{rule.name}" saved.')
        return redirect('alerts:rules_view')

    if rule:
        fields = {f: getattr(rule, f) for f in ('name', 'scope', 'symbol', 'match', 'is_active', 'cooldown_days')}
        form_conditions = [{'metric': c.metric, 'operator': c.operator, 'value': c.value} for c in rule.conditions.all()]
    else:
        fields = {'name': '', 'scope': 'BOTH', 'symbol': '', 'match': 'ALL', 'is_active': True, 'cooldown_days': 7}
        form_conditions = [{'metric': 'yield_vs_5y_avg', 'operator': 'gt', 'value': ''}]
    return render(request, 'alerts/rule_form.html', _rule_form_context(rule, fields, form_conditions))


def _rule_form_context(rule, fields, conditions):
    for c in conditions:
        if c['value'] != '':
            c['value'] = f"{float(c['value']):g}"
    return {
        'rule': rule,
        'fields': fields,
        'conditions': conditions,
        'metrics': METRICS,
        'operators': [(key, symbol) for key, (_, symbol) in OPERATORS.items()],
        'scopes': AlertRule.SCOPE_CHOICES,
        'matches': AlertRule.MATCH_CHOICES,
    }


@login_required
@require_POST
def rule_preview_api(request):
    """Evaluate the (possibly unsaved) rule in the editor against today's data. Read-only."""
    fields, conditions, errors = _parse_rule_form(request.POST)
    errors = [e for e in errors if e != 'Give the rule a name.']
    if errors:
        return JsonResponse({'errors': errors}, status=400)
    rows = preview_rule(request.user, fields['scope'], fields['symbol'], fields['match'], conditions)
    return JsonResponse({'rows': rows})


# --------------------------------------------------------------------------- #
# History                                                                      #
# --------------------------------------------------------------------------- #

@login_required
def history_view(request):
    events = AlertEvent.objects.filter(user=request.user)
    kind = request.GET.get('kind')
    if kind in dict(AlertEvent.KIND_CHOICES):
        events = events.filter(kind=kind)
    return render(request, 'alerts/history.html', {
        'events': events[:200],
        'kinds': AlertEvent.KIND_CHOICES,
        'current_kind': kind,
    })


# --------------------------------------------------------------------------- #
# Notification settings                                                        #
# --------------------------------------------------------------------------- #

@login_required
def notification_settings_view(request):
    prefs = NotificationSettings.for_user(request.user)

    if request.method == 'POST':
        action = request.POST.get('action', 'save')

        if action == 'save':
            for flag in ('email_enabled', 'warn_dividend_cut', 'warn_dividend_freeze', 'warn_payout', 'warn_ex_dividend'):
                setattr(prefs, flag, request.POST.get(flag) == 'on')
            prefs.telegram_enabled = request.POST.get('telegram_enabled') == 'on' and bool(prefs.telegram_chat_id)
            try:
                prefs.ex_dividend_days = min(60, max(1, int(request.POST.get('ex_dividend_days') or 7)))
            except ValueError:
                pass
            prefs.save()
            messages.success(request, 'Notification settings saved.')

        elif action == 'telegram_link':
            prefs.telegram_link_token = secrets.token_urlsafe(16)
            prefs.save(update_fields=['telegram_link_token', 'updated_at'])

        elif action == 'telegram_verify':
            try:
                chat_id = find_telegram_chat_id(prefs.telegram_link_token) if prefs.telegram_link_token else None
            except TelegramError as e:
                messages.error(request, f'Could not reach Telegram: {e}')
                return redirect('alerts:notification_settings_view')
            if chat_id:
                prefs.telegram_chat_id = chat_id
                prefs.telegram_enabled = True
                prefs.telegram_link_token = ''
                prefs.save()
                try:
                    send_telegram(chat_id, '✅ Market Mind connected — your alert digests will arrive here.')
                except TelegramError:
                    pass
                messages.success(request, 'Telegram connected.')
            else:
                messages.error(request, "Didn't find your /start message yet — open the link, press Start, then verify again.")

        elif action == 'telegram_disconnect':
            prefs.telegram_chat_id = ''
            prefs.telegram_enabled = False
            prefs.telegram_link_token = ''
            prefs.save()
            messages.success(request, 'Telegram disconnected.')

        elif action == 'test_email':
            if not request.user.email:
                messages.error(request, 'Your account has no email address — add one in Edit profile.')
            else:
                try:
                    send_mail(
                        subject='[Market Mind] Test alert',
                        message='This is a test — your Market Mind alert digests will arrive at this address.',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[request.user.email],
                        fail_silently=False,
                    )
                    messages.success(request, f'Test email sent to {request.user.email}.')
                except Exception as e:
                    messages.error(request, f'Email failed: {e}')

        elif action == 'test_telegram' and prefs.telegram_chat_id:
            try:
                send_telegram(prefs.telegram_chat_id, 'This is a test — your Market Mind alert digests will arrive here.')
                messages.success(request, 'Test Telegram message sent.')
            except TelegramError as e:
                messages.error(request, f'Telegram failed: {e}')

        return redirect('alerts:notification_settings_view')

    return render(request, 'alerts/notification_settings.html', {
        'prefs': prefs,
        'telegram_configured': telegram_configured(),
        'telegram_link': telegram_link_url(prefs.telegram_link_token) if prefs.telegram_link_token and telegram_configured() else '',
    })
