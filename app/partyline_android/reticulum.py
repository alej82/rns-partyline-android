from .i18n import t
from .paths import is_android
from .rns_config import ensure_config


class SharedInstanceUnavailable(RuntimeError):
    pass


def start_reticulum(rns_dir, require_shared=None):
    import RNS

    if require_shared is None:
        require_shared = is_android()

    if require_shared:
        ensure_config(rns_dir)

    existing = RNS.Reticulum.get_instance()
    if existing is not None:
        instance = existing
    else:
        try:
            instance = RNS.Reticulum(configdir=rns_dir, require_shared_instance=require_shared)
        except Exception as error:
            if require_shared:
                raise SharedInstanceUnavailable(t("reticulum.shared_instance_connect")) from error
            raise

    if require_shared and not getattr(instance, "is_connected_to_shared_instance", False):
        raise SharedInstanceUnavailable(t("reticulum.shared_instance_missing"))

    return instance
