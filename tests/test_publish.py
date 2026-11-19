import os
from pathlib import Path
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/publish.sh"


class PublishGuardsTests(unittest.TestCase):
    def test_rejects_unknown_package_before_accessing_credentials(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "../other-package"],
            env={"PATH": os.environ["PATH"]}, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)

    def test_refuses_publication_without_environment_secret(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "kraken-cli-bin"],
            env={"PATH": os.environ["PATH"]}, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Configure the aur environment secret", result.stderr)


if __name__ == "__main__":
    unittest.main()
