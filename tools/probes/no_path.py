import os, sys, time, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "app"))
import partyline_android
from partyline.client import Client
Client.path_wait_seconds = lambda self: 3
from partyline_android.engine import Engine
e = Engine(rns_dir=os.path.expanduser("~/.config/partyline-dev/client-rns"), config_dir=tempfile.mkdtemp(prefix="nopath-"), display_name="nopath")
e.start(); e.connect("11"*16)
t0=time.time()
while time.time()-t0 < 32:
    s=e.snapshot(); ev=e.drain_events()
    print(f"{time.time()-t0:4.1f}s state={s['connection']['state']} error={s['connection']['error']!r} retry_in={s['connection']['retry_in']} events={[x['type'] for x in ev]}", flush=True)
    time.sleep(1)
e.disconnect(); e.stop()
