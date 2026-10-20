"""Make LXST's bundled pyogg work on Android.

pyogg only defines its ctypes aliases when libogg can be loaded, and it
looks libraries up with ctypes.util.find_library(), which does not work on
Android. LXST does not use libogg itself, but pyogg/opus.py imports the
aliases unconditionally, so importing LXST fails with NameError before the
Opus codec is even reached.

The loader below injects the missing aliases into pyogg.ogg and teaches
pyogg's library loader to try the shared objects packaged in the APK.
"""

import ctypes
import importlib.abc
import importlib.machinery
import sys

_PACKAGE = "LXST.Codecs.libs.pyogg"

_OGG_TYPES = {
    "c_ubyte_p": ctypes.POINTER(ctypes.c_ubyte),
    "c_uchar": ctypes.c_ubyte,
    "c_uchar_p": ctypes.POINTER(ctypes.c_ubyte),
    "c_float_p": ctypes.POINTER(ctypes.c_float),
    "c_float_p_p": ctypes.POINTER(ctypes.POINTER(ctypes.c_float)),
    "c_float_p_p_p": ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(ctypes.c_float))),
    "c_char_p_p": ctypes.POINTER(ctypes.c_char_p),
    "c_int_p": ctypes.POINTER(ctypes.c_int),
    "c_long_p": ctypes.POINTER(ctypes.c_long),
    "ogg_int16_t": ctypes.c_int16,
    "ogg_uint16_t": ctypes.c_uint16,
    "ogg_int32_t": ctypes.c_int32,
    "ogg_uint32_t": ctypes.c_uint32,
    "ogg_int64_t": ctypes.c_int64,
    "ogg_uint64_t": ctypes.c_uint64,
    "ogg_int64_t_p": ctypes.POINTER(ctypes.c_int64),
}


_patched_loaders = set()


def _patch_library_loader(module):
    external = module.ExternalLibrary
    if external in _patched_loaders:
        return
    _patched_loaders.add(external)
    original = external.load_other

    def load_other(name, paths=None, tests=None):
        library = original(name, paths, tests)
        if library is not None:
            return library
        for candidate in (f"lib{name}.so", f"{name}.so"):
            try:
                library = ctypes.CDLL(candidate)
            except OSError:
                continue
            if not tests or all(check(library) for check in tests):
                return library
        return None

    external.load_other = staticmethod(load_other)


class _Loader(importlib.abc.Loader):
    def __init__(self, wrapped, fullname):
        self._wrapped = wrapped
        self._fullname = fullname

    def create_module(self, spec):
        return self._wrapped.create_module(spec)

    def exec_module(self, module):
        self._wrapped.exec_module(module)
        if self._fullname == _PACKAGE + ".ogg":
            for name, value in _OGG_TYPES.items():
                module.__dict__.setdefault(name, value)
        elif self._fullname == _PACKAGE + ".library_loader":
            _patch_library_loader(module)


class _Finder(importlib.abc.MetaPathFinder):
    _targets = (_PACKAGE + ".ogg", _PACKAGE + ".library_loader")

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self._targets:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return None
        spec.loader = _Loader(spec.loader, fullname)
        return spec


_installed = False


def install():
    global _installed
    if _installed:
        return
    _installed = True
    sys.meta_path.insert(0, _Finder())
