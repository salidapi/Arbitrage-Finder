"""Ordinary public-page libraries must not be mistaken for an access challenge."""
import pytest

from arbscanner.connectors.base import SourceBlocked
from arbscanner.connectors.network import detect_challenge


def test_public_odds_with_login_captcha_library_are_not_blocked():
    html = '''<html><head><script src="/captcha-api/assets/hunt-captcha.js"></script>
    <script>const loginError = "Access denied";</script>
    <style>.captcha-help::after { content: "Verify you are human"; }</style></head>
    <body><div class="dashboard-game">Alpha vs Beta 2.50</div>
    <div hidden>Please complete the captcha</div></body></html>'''
    detect_challenge(html)


@pytest.mark.parametrize("html", [
    "Please verify you are human", "Checking your browser", "Access denied",
    "Please complete the captcha", "Solve the captcha to continue",
    '<form id="challenge-form">Confirm access</form>',
    '<script>window._cf_chl_opt = {challenge: true};</script><p>Enable JavaScript</p>',
])
def test_actual_access_challenges_remain_blocked(html):
    with pytest.raises(SourceBlocked):
        detect_challenge(html)
