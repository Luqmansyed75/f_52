print('Smoke publish round')
from core.event_bus import EventBus
bus = EventBus()
print('Bus created')
# publish to known-good subject
bus.publish('meeting.transcript.ready', {'text': 'ok', 'session_id': 's1'})
print('Published ready')
# publish to a subject that may not be in the stream
bus.publish('meeting.speech.started', {'session_id': 's1'})
print('Published speech.started')
# publish to an unknown subject
bus.publish('meeting.unknown.subject', {'x': 1})
print('Published unknown (should log fallback)')
