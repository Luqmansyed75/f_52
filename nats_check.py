import asyncio
import nats
from nats.js.api import StreamConfig

async def main():
    print('Connecting to NATS...')
    nc = await nats.connect('nats://localhost:4222')
    js = nc.jetstream()
    print('Connected to', nc.connected_url)
    try:
        cfg = StreamConfig(name='VOICE_AGENT_STREAM_TEST', subjects=['meeting.>'])
        print('Adding stream', cfg.name)
        await js.add_stream(cfg)
        print('Stream added OK')
    except Exception as e:
        print('add_stream error:', repr(e))
    try:
        # try to publish a test message
        print('Publishing test message')
        await js.publish('meeting.health.check', b'{"ok": true}')
        print('Published OK')
    except Exception as e:
        print('publish error:', repr(e))
    await nc.close()

asyncio.run(main())
