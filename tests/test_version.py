import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from partyline_android import APP_VERSION


def buildozer_version():
    with open(os.path.join(ROOT, "buildozer.spec"), encoding="utf-8") as spec:
        for line in spec:
            match = re.match(r"\s*version\s*=\s*(\S+)", line)
            if match:
                return match.group(1)
    return None


class AppVersionTests(unittest.TestCase):
    def test_app_version_matches_buildozer_spec(self):
        self.assertEqual(APP_VERSION, buildozer_version())


if __name__ == "__main__":
    unittest.main()
