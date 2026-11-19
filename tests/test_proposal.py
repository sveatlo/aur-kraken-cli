import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/propose-update.sh"


class ProposalTests(unittest.TestCase):
    def test_retries_orphaned_branch_without_force_push_or_overwriting_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "checkout"
            repository.mkdir()
            remote = root / "origin.git"
            commands = root / "bin"
            commands.mkdir()
            gh = commands / "gh"
            gh.write_text(
                '#!/usr/bin/env bash\nset -euo pipefail\n'
                'case "$1 $2" in\n'
                '  "pr list") printf "%s\\n" "${PR_STATE:-}" ;;\n'
                '  "auth setup-git") ;;\n'
                '  "pr create")\n'
                '    [[ "$3 $4" == "--base master" ]] || exit 2\n'
                '    if [[ ! -f "$ATTEMPT" ]]; then touch "$ATTEMPT"; exit 1; fi\n'
                '    touch "$CREATED" ;;\n'
                '  *) exit 2 ;;\n'
                'esac\n'
            )
            gh.chmod(0o755)
            env = os.environ | {
                "GIT_CONFIG_GLOBAL": "/dev/null",
                "GIT_CONFIG_NOSYSTEM": "1",
                "PATH": f"{commands}:{os.environ['PATH']}",
                "ATTEMPT": str(root / "attempt"),
                "CREATED": str(root / "created"),
            }

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=repository, env=env, text=True,
                    stderr=subprocess.STDOUT,
                )

            def propose():
                return subprocess.run(
                    ["bash", str(SCRIPT)], cwd=repository, env=env,
                    capture_output=True, text=True,
                )

            subprocess.run(["git", "init", "--bare", "-b", "packaging", str(remote)], check=True, capture_output=True)
            git("init", "-b", "packaging")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            package = repository / "packages/kraken-cli"
            package.mkdir(parents=True)
            recipe = package / "PKGBUILD"
            recipe.write_text("pkgver=0.5.1\n")
            (package / ".SRCINFO").write_text("pkgver = 0.5.1\n")
            git("add", ".")
            git("commit", "-m", "Initial test")
            git("remote", "add", "origin", str(remote))
            git("push", "origin", "packaging")
            recipe.write_text("pkgver=0.5.2\n")
            first = propose()
            self.assertNotEqual(first.returncode, 0)
            pushed = git("ls-remote", "origin", "refs/heads/update/kraken-cli-0.5.2")
            self.assertTrue(pushed)
            git("switch", "packaging")
            recipe.write_text("pkgver=0.5.2\nother=changed\n")
            mismatch = propose()
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("reconcile it manually", mismatch.stderr)
            self.assertEqual(git("ls-remote", "origin", "refs/heads/update/kraken-cli-0.5.2"), pushed)
            recipe.write_text("pkgver=0.5.2\n")
            retry = propose()
            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertTrue((root / "created").exists())
            self.assertEqual(git("ls-remote", "origin", "refs/heads/update/kraken-cli-0.5.2"), pushed)
            (root / "created").unlink()
            env["PR_STATE"] = "CLOSED"
            closed = propose()
            self.assertEqual(closed.returncode, 0, closed.stderr)
            self.assertFalse((root / "created").exists())


if __name__ == "__main__":
    unittest.main()
