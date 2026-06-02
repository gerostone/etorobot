from etorobot.core.bus import EventBus


async def test_subscribers_receive_published_events():
    bus = EventBus()
    received = []
    bus.subscribe("tick", lambda e: received.append(e))
    await bus.publish("tick", 42)
    assert received == [42]


async def test_async_subscriber_is_awaited():
    bus = EventBus()
    received = []

    async def handler(e):
        received.append(e)

    bus.subscribe("tick", handler)
    await bus.publish("tick", "x")
    assert received == ["x"]
