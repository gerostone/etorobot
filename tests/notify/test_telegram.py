# tests/notify/test_telegram.py
import httpx
import respx
from etorobot.notify.base import NullNotifier
from etorobot.notify.telegram import TelegramNotifier


async def test_null_notifier_is_noop():
    n = NullNotifier()
    await n.notify("fill", "anything")  # must not raise


@respx.mock
async def test_telegram_posts_message():
    route = respx.post(
        "https://api.telegram.org/bottoken/sendMessage"
    ).mock(return_value=httpx.Response(200, json={"ok": True}))
    n = TelegramNotifier(token="token", chat_id="42")
    await n.notify("fill", "open BTC")
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["chat_id"] == "42"
    assert "open BTC" in body["text"]
    assert route.called
    await n.aclose()
