import os

MARKER = "# partyline-android managed rns config v1"
SHARED_INSTANCE_PORT = 37428
INSTANCE_CONTROL_PORT = 37429

TEMPLATE = f"""{MARKER}
[reticulum]
  enable_transport = No
  share_instance = Yes
  shared_instance_type = tcp
  shared_instance_port = {SHARED_INSTANCE_PORT}
  instance_control_port = {INSTANCE_CONTROL_PORT}
  instance_name = default
  panic_on_interface_error = No

[logging]
  loglevel = 4

[interfaces]
"""


def config_path(config_dir):
    return os.path.join(config_dir, "config")


def ensure_config(config_dir):
    os.makedirs(config_dir, exist_ok=True)
    path = config_path(config_dir)
    write = True
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as handle:
                write = not handle.read().startswith(MARKER)
        except OSError:
            write = True
    if write:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(TEMPLATE)
    os.chmod(path, 0o600)
    return path
