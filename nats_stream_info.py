import asyncio
import nats

async def main():
    nc = await nats.connect('nats://localhost:4222')
    js = nc.jetstream()
    try:
        info = await js.stream_info('MEETING_EVENTS')
        print('Stream info:', info)
    except Exception as e:
        print('stream_info error:', repr(e))
    await nc.close()

asyncio.run(main())
