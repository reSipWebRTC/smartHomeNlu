from __future__ import annotations

from runtime.event_bus import InMemoryEventBus


def test_event_bus_ring_buffer_per_topic() -> None:
    bus = InMemoryEventBus(max_events_per_topic=3)

    for i in range(5):
        bus.publish("evt.test", {"idx": i})

    events = bus.events("evt.test")
    assert len(events) == 3
    assert [item["idx"] for item in events] == [2, 3, 4]


def test_event_bus_ring_buffer_isolated_by_topic() -> None:
    bus = InMemoryEventBus(max_events_per_topic=2)

    for i in range(4):
        bus.publish("evt.a", {"idx": i})
    bus.publish("evt.b", {"idx": 100})

    assert [item["idx"] for item in bus.events("evt.a")] == [2, 3]
    assert [item["idx"] for item in bus.events("evt.b")] == [100]
