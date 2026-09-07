from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bootstrap.sh"


class BootstrapMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.home = pathlib.Path(self.tempdir.name) / "home"
        self.home.mkdir()
        self.bin = pathlib.Path(self.tempdir.name) / "bin"
        self.bin.mkdir()
        self.write_fake_commands()

    def write_fake_commands(self) -> None:
        fake_git = self.bin / "git"
        fake_git.write_text(
            "#!/usr/bin/env bash\n"
            'printf \'%s\\n\' "$*" >> "$HOME/git.args"\n'
            'if [ "${FAKE_PSTACK_FETCH_FAILURE:-}" != "" ] && [ "${3:-}" = fetch ]; then exit 1; fi\n'
            'if [ "${3:-}" = ls-remote ]; then\n'
            '  if [ "${FAKE_PSTACK_FETCH_FAILURE:-}" = transport ]; then exit 1; fi\n'
            '  if [ "${FAKE_PSTACK_FETCH_FAILURE:-}" = fetch-error ]; then printf "%s\\trefs/heads/main\\n" "$5"; fi\n'
            '  exit 0\n'
            'fi\n'
            "exit 0\n"
        )
        fake_git.chmod(0o755)
        fake_python = self.bin / "python3"
        fake_python.write_text("#!/usr/bin/env bash\nexit 0\n")
        fake_python.chmod(0o755)

    def create_legacy_checkout(self) -> pathlib.Path:
        legacy = self.home / ("agents" + "-cfg")
        legacy.mkdir()
        (legacy / ".git").mkdir()
        (legacy / "pstack-revision.txt").write_text("0" * 40 + "\n")
        (legacy / "bin").mkdir()
        (legacy / "bin" / "skills-sync").symlink_to(ROOT / "bin" / "skills-sync")
        installer = legacy / "install.sh"
        installer.write_text(
            "#!/usr/bin/env bash\n"
            'printf \'%s\\n\' "$0" > "$HOME/install.path"\n'
            "exit 0\n"
        )
        installer.chmod(0o755)
        return legacy

    def run_bootstrap(self) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("IMPSTACK_DIR", None)
        env.pop("IMPSTACK_REPO", None)
        env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.bin}:{os.defpath}",
                "PSTACK_DIR": str(self.home / "pstack"),
                "PRIVATE_CONFIG": str(self.home / "private"),
            }
        )
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_migrates_legacy_path_without_overwriting_new_entries(self) -> None:
        legacy = self.create_legacy_checkout()
        new = self.home / "impstack"

        migrated = self.run_bootstrap()

        self.assertEqual(migrated.returncode, 0, migrated.stderr + migrated.stdout)
        self.assertTrue(new.is_symlink())
        self.assertEqual(new.resolve(), legacy)
        link_line = f"== linked legacy checkout: {new} -> {legacy}"
        self.assertIn(link_line, migrated.stdout)
        self.assertIn(
            f"-C {new} pull --ff-only",
            (self.home / "git.args").read_text(),
        )
        self.assertEqual(
            (self.home / "install.path").read_text().strip(),
            str(new / "install.sh"),
        )

        repeated = self.run_bootstrap()

        self.assertEqual(repeated.returncode, 0, repeated.stderr + repeated.stdout)
        self.assertTrue(new.is_symlink())
        self.assertNotIn(link_line, repeated.stdout)

        new.unlink()
        new.mkdir()
        (new / ".git").mkdir()
        (new / "pstack-revision.txt").write_text("0" * 40 + "\n")
        (new / "bin").mkdir()
        (new / "bin" / "skills-sync").symlink_to(ROOT / "bin" / "skills-sync")
        installer = new / "install.sh"
        installer.write_text("#!/usr/bin/env bash\nexit 0\n")
        installer.chmod(0o755)
        marker = new / "keep-me"
        marker.write_text("existing")

        existing = self.run_bootstrap()

        self.assertEqual(existing.returncode, 0, existing.stderr + existing.stdout)
        self.assertTrue(new.is_dir())
        self.assertFalse(new.is_symlink())
        self.assertEqual(marker.read_text(), "existing")
        self.assertNotIn(link_line, existing.stdout)

        shutil.rmtree(new)
        new.write_text("existing file")

        existing_file = self.run_bootstrap()

        self.assertNotEqual(existing_file.returncode, 0)
        self.assertTrue(new.is_file())
        self.assertEqual(new.read_text(), "existing file")
        self.assertNotIn(link_line, existing_file.stdout)

        new.unlink()
        dangling_target = self.home / "missing-impstack"
        new.symlink_to(dangling_target)

        dangling = self.run_bootstrap()

        self.assertNotEqual(dangling.returncode, 0)
        self.assertTrue(new.is_symlink())
        self.assertEqual(os.readlink(new), str(dangling_target))
        self.assertNotIn(link_line, dangling.stdout)

    def test_default_bridge_is_created_when_custom_checkout_is_selected(self) -> None:
        legacy = self.create_legacy_checkout()
        custom = self.home / "custom-checkout"
        custom.mkdir()
        (custom / ".git").mkdir()
        (custom / "pstack-revision.txt").write_text("0" * 40 + "\n")
        (custom / "bin").mkdir()
        (custom / "bin" / "skills-sync").symlink_to(ROOT / "bin" / "skills-sync")
        installer = custom / "install.sh"
        installer.write_text("#!/usr/bin/env bash\nexit 0\n")
        installer.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.bin}:{os.defpath}",
                "PSTACK_DIR": str(self.home / "pstack"),
                "PRIVATE_CONFIG": str(self.home / "private"),
                "IMPSTACK_DIR": str(custom),
            }
        )
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        new = self.home / "impstack"
        link_line = f"== linked legacy checkout: {new} -> {legacy}"
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(new.is_symlink())
        self.assertEqual(new.resolve(), legacy)
        self.assertIn(link_line, result.stdout)
        self.assertTrue(custom.is_dir())
        self.assertFalse(custom.is_symlink())

    def test_new_pstack_checkout_fetches_only_the_pinned_revision(self) -> None:
        self.create_legacy_checkout()

        result = self.run_bootstrap()

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        commands = (self.home / "git.args").read_text().splitlines()
        self.assertTrue(any(command.startswith("init ") for command in commands), commands)
        self.assertTrue(
            any(" fetch --depth 1 origin " + "0" * 40 in command for command in commands),
            commands,
        )
        self.assertFalse(any(command.startswith("clone ") and "pstack" in command for command in commands))

    def test_pstack_fetch_failure_does_not_claim_an_unproven_cause(self) -> None:
        self.create_legacy_checkout()
        env = os.environ.copy()
        env.update(
            HOME=str(self.home),
            PATH=f"{self.bin}:{os.defpath}",
            PSTACK_DIR=str(self.home / "pstack"),
            PRIVATE_CONFIG=str(self.home / "private"),
            FAKE_PSTACK_FETCH_FAILURE="missing-ref",
        )

        result = subprocess.run(
            ["bash", str(SCRIPT)], cwd=ROOT, env=env,
            text=True, capture_output=True, check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not fetch pinned pstack revision", result.stderr)
        self.assertIn("may be missing", result.stderr)
        self.assertIn("may restrict direct revision fetches", result.stderr)
        self.assertIn(str(self.home / "impstack/pstack-revision.txt"), result.stderr)
