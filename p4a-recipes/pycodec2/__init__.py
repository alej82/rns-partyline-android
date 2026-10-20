from os.path import join

from pythonforandroid.recipe import CythonRecipe, Recipe


class PyCodec2Recipe(CythonRecipe):
    version = "4.1.1"
    url = (
        "https://files.pythonhosted.org/packages/33/53/"
        "76151cb79283909bf6b1751ea728565bea4014efc090e83af94175e99c7d/"
        "pycodec2-{version}.tar.gz"
    )
    name = "pycodec2"
    site_packages_name = "pycodec2"
    depends = ["setuptools", "numpy", "libcodec2"]

    def get_recipe_env(self, arch=None, with_flags_in_cc=True):
        if arch is None:
            raise RuntimeError("arch is required")
        env = super().get_recipe_env(arch, with_flags_in_cc)
        codec2 = Recipe.get_recipe("libcodec2", self.ctx)
        prefix = join(codec2.get_build_dir(arch.arch), "build_android", "install")
        env["CFLAGS"] = env.get("CFLAGS", "") + f" -I{join(prefix, 'include')}"
        env["LDFLAGS"] = env.get("LDFLAGS", "") + f" -L{join(prefix, 'lib')} -lcodec2"
        return env


recipe = PyCodec2Recipe()
