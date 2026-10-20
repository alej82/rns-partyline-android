import os
import re
from multiprocessing import cpu_count
from os.path import join

import sh
from pythonforandroid.logger import shprint
from pythonforandroid.recipe import Recipe
from pythonforandroid.util import current_directory, ensure_dir

HOST_MARKER = "# partyline codec2 host generator"


class Codec2Recipe(Recipe):
    version = "1.2.0"
    url = "https://github.com/drowe67/codec2/archive/{version}.tar.gz"
    built_libraries = {"libcodec2.so": "build_android/install/lib"}

    def _build_host_generator(self, source):
        build = join(source, "build_host")
        ensure_dir(build)
        host_env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("CC", "CXX", "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS", "AR", "RANLIB", "STRIP")
        }
        with current_directory(build):
            shprint(
                sh.cmake,
                source,
                "-DCMAKE_BUILD_TYPE=Release",
                "-DUNITTEST=OFF",
                "-DLPCNET=OFF",
                _env=host_env,
            )
            shprint(sh.make, "generate_codebook", f"-j{cpu_count()}", _env=host_env)
        generator = join(build, "src", "generate_codebook")
        if not os.path.isfile(generator):
            raise RuntimeError(f"codec2 host generator not found at {generator}")
        return generator

    def _use_host_generator(self, source, generator):
        path = join(source, "src", "CMakeLists.txt")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        if HOST_MARKER in text:
            if "else(CMAKE_CROSSCOMPILING)" in text:
                text = re.sub(
                    r"else\(CMAKE_CROSSCOMPILING\).*?endif\(CMAKE_CROSSCOMPILING\)",
                    "",
                    text,
                    count=1,
                    flags=re.S,
                )
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(text)
            return
        replacement = (
            f"{HOST_MARKER}\n"
            "add_executable(generate_codebook IMPORTED)\n"
            f'set_target_properties(generate_codebook PROPERTIES IMPORTED_LOCATION "{generator}")\n'
        )
        updated, count = re.subn(
            r"if\(CMAKE_CROSSCOMPILING\).*?endif\(CMAKE_CROSSCOMPILING\)",
            replacement,
            text,
            count=1,
            flags=re.S,
        )
        if count != 1:
            raise RuntimeError("could not patch codec2 CMakeLists.txt for cross compilation")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(updated)

    def build_arch(self, arch):
        source = self.get_build_dir(arch.arch)
        generator = self._build_host_generator(source)
        self._use_host_generator(source, generator)

        build = join(source, "build_android")
        ensure_dir(build)
        toolchain = join(self.ctx.ndk_dir, "build/cmake/android.toolchain.cmake")
        install = join(build, "install")
        env = self.get_recipe_env(arch)
        with current_directory(build):
            shprint(
                sh.cmake,
                source,
                "-DCMAKE_TOOLCHAIN_FILE=" + toolchain,
                "-DANDROID_ABI=" + arch.arch,
                "-DANDROID_PLATFORM=android-" + str(self.ctx.ndk_api),
                "-DCMAKE_BUILD_TYPE=Release",
                "-DBUILD_SHARED_LIBS=ON",
                "-DUNITTEST=OFF",
                "-DLPCNET=OFF",
                "-DCMAKE_INSTALL_PREFIX=" + install,
                _env=env,
            )
            shprint(sh.make, f"-j{cpu_count()}", _env=env)
            shprint(sh.make, "install", _env=env)


recipe = Codec2Recipe()
