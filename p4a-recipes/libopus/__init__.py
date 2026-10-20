from multiprocessing import cpu_count

import sh
from pythonforandroid.recipe import Recipe
from pythonforandroid.toolchain import current_directory, shprint


class OpusRecipe(Recipe):
    version = "1.4"
    url = "https://downloads.xiph.org/releases/opus/opus-{version}.tar.gz"
    built_libraries = {"libopus.so": ".libs"}

    def build_arch(self, arch):
        with current_directory(self.get_build_dir(arch.arch)):
            env = self.get_recipe_env(arch)
            configure = sh.Command("./configure")
            shprint(
                configure,
                f"--host={arch.command_prefix}",
                "--disable-static",
                "--enable-shared",
                "--disable-doc",
                "--disable-extra-programs",
                "--disable-stack-protector",
                "--with-pic",
                _env=env,
            )
            shprint(sh.make, "-j", str(cpu_count()), _env=env)


recipe = OpusRecipe()
