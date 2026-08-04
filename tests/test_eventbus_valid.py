print('Testing EventBus with valid subject...')
from core.event_bus import EventBus
bus = EventBus()
print('Created EventBus')
bus.publish('meeting.transcript.ready', {'text': 'hello', 'session_id': 'test'})
print('Publish attempted')
