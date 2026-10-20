import os


def is_android():
    return bool(os.environ.get("ANDROID_PRIVATE") or os.environ.get("ANDROID_APP_PATH"))


def android_home():
    for key in ("ANDROID_PRIVATE", "ANDROID_APP_PATH"):
        value = os.environ.get(key)
        if value:
            return os.path.abspath(value)
    raise RuntimeError("not running on Android")


def app_home():
    if is_android():
        return android_home()
    return os.path.join(os.path.expanduser("~"), ".partyline-android")


def prepare_environment():
    home = app_home()
    os.makedirs(home, exist_ok=True)
    if is_android():
        os.environ["HOME"] = home
    os.environ.setdefault("PARTYLINE_CONFIG_DIR", os.path.join(home, "partyline"))
    os.environ.setdefault("PARTYLINE_RNS_DIR", os.path.join(home, "rns"))
    return home
