import os, sys, time, tempfile
sys.path.insert(0, "<home>/partyline-android/app")
import partyline_android
from partyline_android.engine import Engine
e = Engine(rns_dir=os.path.expanduser("~/.config/partyline-dev/client-rns"), config_dir=tempfile.mkdtemp(prefix="deny-"), display_name="deny-client")
e.start(); e.connect("00000000000000000000000000000000", server_password="incorrecta")
t0=time.time()
while time.time()-t0 < 30:
    s=e.snapshot(); ev=e.drain_events()
    if ev or int(time.time()-t0)%5==0:
        c=s["connection"]
        print(f"{time.time()-t0:4.1f}s state={c['state']} kicked={c['kicked']} error={c['error']!r} retry_in={c['retry_in']} events={[x['type'] for x in ev]}", flush=True)
    time.sleep(1)
e.disconnect(); e.stop()
