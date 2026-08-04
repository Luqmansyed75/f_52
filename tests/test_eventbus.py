print("Testing EventBus...")
try:
    from core.event_bus import EventBus
    bus = EventBus()
    print("EventBus created OK")
    bus.publish("meeting.health.check", {"ok": True})
    print("Publish attempted")
except Exception as e:
    print("EventBus error:", repr(e))
