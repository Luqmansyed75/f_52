import time, threading, traceback
from core.event_bus import EventBus
import asyncio

print('Creating EventBus...')
bus = EventBus()
print('EventBus thread:', getattr(bus, '_thread'))
thr = bus._thread
print('Thread name:', thr.name, 'alive:', thr.is_alive(), 'ident:', thr.ident, 'daemon:', thr.daemon)
loop = bus._loop
print('Loop object:', loop)
print('Loop is_running():', loop.is_running())

# schedule a quick coroutine
print('Submitting quick sleep coroutine...')
fut = asyncio.run_coroutine_threadsafe(asyncio.sleep(0.01, result='ok'), loop)
try:
    print('Quick future result:', fut.result(timeout=2))
except Exception as e:
    print('Quick future failed:', repr(e))

# Inspect tasks on the loop by scheduling a coroutine that runs inside the loop
async def inspect_tasks():
    import asyncio, traceback
    tasks = list(asyncio.all_tasks())
    out = []
    for t in tasks:
        try:
            stack = []
            for fr in t.get_stack(limit=5):
                stack.append(''.join(traceback.format_list(traceback.extract_stack(fr))))
        except Exception as e:
            stack = [f'error getting stack: {e}']
        out.append({'task': repr(t), 'done': t.done(), 'stack': stack})
    return out

print('Inspecting tasks on event loop...')
inspect_fut = asyncio.run_coroutine_threadsafe(inspect_tasks(), loop)
try:
    tasks_info = inspect_fut.result(timeout=5)
    print('Found', len(tasks_info), 'tasks on loop')
    for i, info in enumerate(tasks_info[:20]):
        print('--- Task', i)
        print(info['task'])
        print('done:', info['done'])
        for s in info['stack']:
            print(s)
except Exception as e:
    print('Inspect tasks failed:', repr(e))

# Submit a blocking coroutine that uses time.sleep to simulate a blocking handler
async def blocking():
    import time
    print('Blocking coroutine started')
    time.sleep(6)
    print('Blocking coroutine finished')

print('Submitting blocking coroutine (6s)')
blk = asyncio.run_coroutine_threadsafe(blocking(), loop)
# give it a moment to start
time.sleep(0.5)
# Now submit another quick coroutine and time how long it takes
import time as _t
start = _t.perf_counter()
quick = asyncio.run_coroutine_threadsafe(asyncio.sleep(0.01, result='fast'), loop)
try:
    res = quick.result(timeout=2)
    took = _t.perf_counter()-start
    print('Quick after blocking result:', res, 'took:', took)
except Exception as e:
    print('Quick after blocking failed:', repr(e))

print('Waiting for blocking to finish...')
try:
    blk.result(timeout=10)
except Exception as e:
    print('Blocking future result/timeout:', repr(e))

print('Done diagnostics')
