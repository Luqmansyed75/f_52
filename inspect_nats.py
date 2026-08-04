import inspect
import nats
from nats.js.client import JetStreamContext
from nats.js.api import ConsumerConfig, DeliverPolicy

print('nats version', getattr(nats, '__version__', 'unknown'))
print('JetStreamContext.pull_subscribe signature:')
print(inspect.signature(JetStreamContext.pull_subscribe))
print('ConsumerConfig signature:')
print(inspect.signature(ConsumerConfig))
print('DeliverPolicy values:', [p for p in dir(DeliverPolicy) if not p.startswith('_')])
