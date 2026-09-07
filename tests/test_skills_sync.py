from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shlex
import shutil
import socket
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "skills-sync"


class SkillsSyncTests(unittest.TestCase):
    def skill_entry(self, name: str) -> dict[str, str]:
        return {
            "source": f"example/{name}",
            "sourceType": "github",
            "sourceUrl": f"https://example.test/{name}.git",
            "skillPath": "SKILL.md",
        }

    def make_home(self) -> tuple[tempfile.TemporaryDirectory[str], pathlib.Path]:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        home = pathlib.Path(tempdir.name) / "home"
        home.mkdir()
        return tempdir, home

    def write_lock(
        self, home: pathlib.Path, skills: dict[str, dict[str, object]]
    ) -> pathlib.Path:
        lock = home / ".agents" / ".skill-lock.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(
            json.dumps(
                {
                    "version": 3,
                    "skills": skills,
                    "dismissed": ["machine-state"],
                    "lastSelectedAgents": ["codex"],
                }
            )
        )
        return lock

    def write_catalog(
        self, repo: pathlib.Path, skills: dict[str, dict[str, str]]
    ) -> pathlib.Path:
        catalog = repo / "skills-catalog.json"
        catalog.write_text(json.dumps({"skills": skills}, indent=2) + "\n")
        return catalog

    def run_cli(
        self,
        repo: pathlib.Path,
        home: pathlib.Path,
        *args: str,
        path: str | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["IMPSTACK_DIR"] = str(repo)
        env["SHARED_SKILLS"] = str(home / ".agents" / "skills")
        env.pop("XDG_STATE_HOME", None)
        if path is not None:
            env["PATH"] = path
            for name in (
                "NVM_BIN",
                "MISE_DATA_DIR",
                "ASDF_DATA_DIR",
                "HOMEBREW_PREFIX",
            ):
                env.pop(name, None)
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            ["/usr/bin/python3", str(SCRIPT), *args],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def create_skill(self, home: pathlib.Path, name: str) -> None:
        skill = home / ".agents" / "skills" / name
        skill.mkdir(parents=True, exist_ok=True)
        (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\n")

    def git(self, cwd: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
        )

    def make_sync_repositories(
        self,
    ) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
        root = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(root))
        remote = root / "remote.git"
        seed = root / "seed"
        actor = root / "actor"
        competitor = root / "competitor"
        self.git(root, "init", "--bare", "--initial-branch=main", str(remote))
        self.git(root, "init", "--initial-branch=main", str(seed))
        self.git(seed, "config", "user.name", "Skills Sync Test")
        self.git(seed, "config", "user.email", "skills-sync@example.test")
        self.write_catalog(seed, {})
        (seed / "bin").mkdir()
        update = seed / "bin" / "skills-update"
        update.write_text("#!/usr/bin/env bash\nset -euo pipefail\n")
        update.chmod(0o755)
        self.git(seed, "add", ".")
        self.git(seed, "commit", "-m", "initial")
        self.git(seed, "remote", "add", "origin", str(remote))
        self.git(seed, "push", "-u", "origin", "main")
        self.git(root, "clone", str(remote), str(actor))
        self.git(root, "clone", str(remote), str(competitor))
        for clone in (actor, competitor):
            self.git(clone, "config", "user.name", "Skills Sync Test")
            self.git(clone, "config", "user.email", "skills-sync@example.test")
        return remote, actor, competitor

    def commit_catalog(
        self, repo: pathlib.Path, skills: dict[str, dict[str, str]], message: str
    ) -> None:
        self.write_catalog(repo, skills)
        self.git(repo, "add", "skills-catalog.json")
        self.git(repo, "commit", "-m", message)

    def test_normalize_is_deterministic_and_strips_volatile_fields(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        self.write_lock(
            home,
            {
                "zeta": {
                    "updatedAt": "tomorrow",
                    "sourceUrl": "https://example.test/zeta.git",
                    "source": "example/zeta",
                    "computedHash": "machine-two",
                    "sourceType": "github",
                    "skillPath": "skills/zeta/SKILL.md",
                },
                "alpha": {
                    "installedAt": "yesterday",
                    "skillFolderHash": "machine-one",
                    "skillPath": "SKILL.md",
                    "sourceType": "github",
                    "source": "example/alpha",
                    "sourceUrl": "https://example.test/alpha.git",
                },
            },
        )

        first = self.run_cli(repo, home, "normalize")
        first_bytes = (repo / "skills-catalog.json").read_bytes()
        second = self.run_cli(repo, home, "normalize")

        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(first_bytes, (repo / "skills-catalog.json").read_bytes())
        self.assertEqual(
            (repo / "skills-catalog.json").read_text(),
            textwrap.dedent(
                """\
                {
                  "skills": {
                    "alpha": {
                      "source": "example/alpha",
                      "sourceType": "github",
                      "sourceUrl": "https://example.test/alpha.git",
                      "skillPath": "SKILL.md"
                    },
                    "zeta": {
                      "source": "example/zeta",
                      "sourceType": "github",
                      "sourceUrl": "https://example.test/zeta.git",
                      "skillPath": "skills/zeta/SKILL.md"
                    }
                  }
                }
                """
            ),
        )

    def test_check_detects_missing_catalog_folder(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        self.write_catalog(
            repo,
            {
                "missing": {
                    "source": "example/skills",
                    "sourceType": "github",
                    "sourceUrl": "https://example.test/skills.git",
                    "skillPath": "skills/missing/SKILL.md",
                }
            },
        )
        (home / ".agents" / "skills").mkdir(parents=True)

        result = self.run_cli(repo, home, "check")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing catalog skill: missing", result.stdout)

    def test_check_detects_extra_installer_managed_folder(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        self.write_catalog(repo, {})
        self.create_skill(home, "extra")

        result = self.run_cli(repo, home, "check")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("uncatalogued installed skill: extra", result.stdout)

    def test_check_ignores_matching_folder_and_reports_other_extra(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        self.write_catalog(repo, {})
        (repo / "skills-ignore.txt").write_text("# managed separately\nlark-*\n")
        self.create_skill(home, "lark-calendar")
        self.create_skill(home, "unknown-skill")

        result = self.run_cli(repo, home, "check")

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("uncatalogued installed skill: lark-calendar", result.stdout)
        self.assertIn("uncatalogued installed skill: unknown-skill", result.stdout)

    def test_normalize_excludes_ignored_live_lock_entry(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        (repo / "skills-ignore.txt").write_text("# managed separately\nlark-*\n")
        self.write_lock(
            home,
            {
                "alpha": {
                    "source": "example/alpha",
                    "sourceType": "github",
                    "sourceUrl": "https://example.test/alpha.git",
                    "skillPath": "SKILL.md",
                },
                "lark-calendar": {
                    "source": "larksuite/lark-calendar",
                    "sourceType": "github",
                    "sourceUrl": "https://example.test/lark-calendar.git",
                    "skillPath": "SKILL.md",
                },
            },
        )

        result = self.run_cli(repo, home, "normalize")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        skills = json.loads((repo / "skills-catalog.json").read_text())["skills"]
        self.assertEqual(list(skills), ["alpha"])

    def test_normalize_preserves_cataloged_download_archive(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        archive = {
            "source": "https://codeload.github.com/example/skills/tar.gz/abc123",
            "sourceType": "download",
            "sourceUrl": "https://codeload.github.com/example/skills/tar.gz/abc123",
            "skillPath": "skills/archive-skill/SKILL.md",
        }
        self.write_catalog(repo, {"archive-skill": archive})
        self.write_lock(home, {})

        result = self.run_cli(repo, home, "normalize")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        skills = json.loads((repo / "skills-catalog.json").read_text())["skills"]
        self.assertEqual(skills, {"archive-skill": archive})

    def test_normalize_requires_explicit_catalog_removals(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        retained = {
            "source": "example/retained",
            "sourceType": "github",
            "sourceUrl": "https://example.test/retained.git",
            "skillPath": "SKILL.md",
        }
        self.write_catalog(repo, {"retained": retained})
        self.write_lock(home, {})

        protected = self.run_cli(repo, home, "normalize")

        self.assertEqual(protected.returncode, 0, protected.stderr + protected.stdout)
        self.assertIn(
            "would remove catalog skill without --allow-removals: retained; preserving",
            protected.stdout,
        )
        skills = json.loads((repo / "skills-catalog.json").read_text())["skills"]
        self.assertEqual(skills, {"retained": retained})

        allowed = self.run_cli(repo, home, "normalize", "--allow-removals")

        self.assertEqual(allowed.returncode, 0, allowed.stderr + allowed.stdout)
        skills = json.loads((repo / "skills-catalog.json").read_text())["skills"]
        self.assertEqual(skills, {})

    def test_normalize_prefers_xdg_state_lockfile(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        self.write_catalog(repo, {})
        self.write_lock(home, {"legacy": self.skill_entry("legacy")})
        xdg_state = home / "state"
        xdg_lock = xdg_state / "skills" / ".skill-lock.json"
        xdg_lock.parent.mkdir(parents=True)
        xdg_lock.write_text(json.dumps({"version": 3, "skills": {"xdg": self.skill_entry("xdg")}}))

        result = self.run_cli(
            repo,
            home,
            "normalize",
            env_overrides={"XDG_STATE_HOME": str(xdg_state)},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        skills = json.loads((repo / "skills-catalog.json").read_text())["skills"]
        self.assertEqual(list(skills), ["xdg"])

    def test_check_exits_nonzero_for_broken_catalog(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        (repo / "skills-catalog.json").write_text('{"skills": {"broken": {}}}\n')
        (home / ".agents" / "skills").mkdir(parents=True)

        result = self.run_cli(repo, home, "check")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken catalog entry: broken", result.stderr)

    def test_run_is_idempotent_on_second_pass(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        fakebin = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(fakebin))
        self.write_catalog(repo, {})
        self.write_lock(
            home,
            {
                "alpha": {
                    "source": "example/alpha",
                    "sourceType": "github",
                    "sourceUrl": "https://example.test/alpha.git",
                    "skillPath": "SKILL.md",
                }
            },
        )
        self.create_skill(home, "alpha")
        (repo / "bin").mkdir()
        update = repo / "bin" / "skills-update"
        update.write_text(
            '#!/usr/bin/env bash\nset -euo pipefail\nprintf \'update %s\\n\' "$*" >> "$HOME/actions"\n'
        )
        update.chmod(0o755)
        git = fakebin / "git"
        git.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'printf \'git %s\\n\' "$*" >> "$HOME/actions"\n'
        )
        git.chmod(0o755)
        npx = fakebin / "npx"
        npx.write_text("#!/usr/bin/env bash\nexit 0\n")
        npx.chmod(0o755)
        path = f"{fakebin}:/usr/bin:/bin"

        first = self.run_cli(repo, home, "run", "--no-update", "--no-push", path=path)
        second = self.run_cli(repo, home, "run", "--no-update", "--no-push", path=path)

        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        actions = (home / "actions").read_text().splitlines()
        self.assertEqual(sum(" commit " in f" {line} " for line in actions), 1)
        self.assertIn("catalog unchanged", second.stdout)

    def test_run_recovers_from_push_race_with_real_git(self) -> None:
        _, actor, competitor = self.make_sync_repositories()
        _, home = self.make_home()
        fakebin = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(fakebin))
        npx = fakebin / "npx"
        npx.write_text("#!/usr/bin/env bash\nexit 0\n")
        npx.chmod(0o755)
        self.write_lock(home, {"beta": self.skill_entry("beta")})
        self.create_skill(home, "beta")
        self.commit_catalog(
            competitor,
            {"alpha": self.skill_entry("alpha")},
            "chore(skills): sync from competitor",
        )
        hook = actor / ".git" / "hooks" / "pre-push"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'if [ ! -e "$HOME/race-fired" ]; then\n'
            '  : > "$HOME/race-fired"\n'
            '  mkdir -p "$HOME/.agents/skills/alpha"\n'
            "  printf '%s\\n' '---' 'name: alpha' 'description: test' '---' "
            '> "$HOME/.agents/skills/alpha/SKILL.md"\n'
            '  git -C "$COMPETITOR" push origin main\n'
            "fi\n"
        )
        hook.chmod(0o755)

        result = self.run_cli(
            actor,
            home,
            "run",
            "--no-update",
            path=f"{fakebin}:/usr/bin:/bin",
            env_overrides={"COMPETITOR": str(competitor)},
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("push rejected; retrying sync once", result.stdout)
        skills = json.loads((actor / "skills-catalog.json").read_text())["skills"]
        self.assertEqual(list(skills), ["alpha", "beta"])

    def test_run_recovers_diverged_generated_commit_with_real_git(self) -> None:
        _, actor, competitor = self.make_sync_repositories()
        _, home = self.make_home()
        fakebin = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(fakebin))
        npx = fakebin / "npx"
        npx.write_text("#!/usr/bin/env bash\nexit 0\n")
        npx.chmod(0o755)
        self.write_lock(home, {"beta": self.skill_entry("beta")})
        self.create_skill(home, "alpha")
        self.create_skill(home, "beta")
        self.commit_catalog(
            actor,
            {"beta": self.skill_entry("beta")},
            "chore(skills): sync from actor",
        )
        self.commit_catalog(
            competitor,
            {"alpha": self.skill_entry("alpha")},
            "chore(skills): sync from competitor",
        )
        self.git(competitor, "push", "origin", "main")

        result = self.run_cli(
            actor,
            home,
            "run",
            "--no-update",
            path=f"{fakebin}:/usr/bin:/bin",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("pull found only generated sync commits; recovering", result.stdout)
        skills = json.loads((actor / "skills-catalog.json").read_text())["skills"]
        self.assertEqual(list(skills), ["alpha", "beta"])

    def test_run_refuses_to_discard_diverged_manual_commit(self) -> None:
        _, actor, competitor = self.make_sync_repositories()
        _, home = self.make_home()
        fakebin = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(fakebin))
        npx = fakebin / "npx"
        npx.write_text("#!/usr/bin/env bash\nexit 0\n")
        npx.chmod(0o755)
        self.write_lock(home, {})
        (home / ".agents" / "skills").mkdir(parents=True)
        (actor / "manual.txt").write_text("keep\n")
        self.git(actor, "add", "manual.txt")
        self.git(actor, "commit", "-m", "chore(skills): sync from impostor")
        (competitor / "remote.txt").write_text("new\n")
        self.git(competitor, "add", "remote.txt")
        self.git(competitor, "commit", "-m", "remote work")
        self.git(competitor, "push", "origin", "main")

        result = self.run_cli(
            actor,
            home,
            "run",
            "--no-update",
            path=f"{fakebin}:/usr/bin:/bin",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "refusing to discard non-sync local commits after pull failure",
            result.stderr,
        )
        self.assertTrue((actor / "manual.txt").is_file())

    def test_run_keeps_generated_commit_when_push_failure_is_not_a_race(self) -> None:
        _, actor, _ = self.make_sync_repositories()
        _, home = self.make_home()
        fakebin = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(fakebin))
        npx = fakebin / "npx"
        npx.write_text("#!/usr/bin/env bash\nexit 0\n")
        npx.chmod(0o755)
        self.write_lock(home, {"alpha": self.skill_entry("alpha")})
        self.create_skill(home, "alpha")
        hook = actor / ".git" / "hooks" / "pre-push"
        hook.write_text("#!/usr/bin/env bash\nexit 9\n")
        hook.chmod(0o755)

        result = self.run_cli(
            actor,
            home,
            "run",
            "--no-update",
            path=f"{fakebin}:/usr/bin:/bin",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("push failed without an upstream race", result.stderr)
        subject = self.git(actor, "log", "-1", "--format=%s").stdout.strip()
        self.assertTrue(subject.startswith("chore(skills): sync"))

    def test_install_missing_uses_catalog_source(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        fakebin = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(fakebin))
        self.write_catalog(
            repo,
            {
                "alpha": {
                    "source": "example/alpha",
                    "sourceType": "github",
                    "sourceUrl": "https://example.test/alpha.git",
                    "skillPath": "SKILL.md",
                }
            },
        )
        npx = fakebin / "npx"
        npx.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            '[ "$1" = --yes ] || { echo "npx --yes must precede the package" >&2; exit 64; }\n'
            'printf \'%s\\n\' "$*" > "$HOME/npx.args"\n'
            'mkdir -p "$HOME/.agents/skills/alpha"\n'
            "printf '%s\\n' '---' 'name: alpha' 'description: test' '---' "
            '> "$HOME/.agents/skills/alpha/SKILL.md"\n'
        )
        npx.chmod(0o755)

        result = self.run_cli(
            repo,
            home,
            "install-missing",
            path=f"{fakebin}:/usr/bin:/bin",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(
            (home / "npx.args").read_text(),
            "--yes skills add example/alpha --skill alpha -g -y\n",
        )
        self.assertTrue((home / ".agents" / "skills" / "alpha" / "SKILL.md").is_file())

    def test_install_missing_continues_after_a_skill_fails(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        fakebin = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(fakebin))
        self.write_catalog(
            repo,
            {name: self.skill_entry(name) for name in ("alpha", "beta", "gamma")},
        )
        npx = fakebin / "npx"
        npx.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            '[ "$1" = --yes ] || exit 64\n'
            'printf \'%s\\n\' "$6" >> "$HOME/attempts"\n'
            'if [ "$6" = beta ]; then exit 7; fi\n'
            'mkdir -p "$HOME/.agents/skills/$6"\n'
            "printf '%s\\n' '---' \"name: $6\" 'description: test' '---' "
            '> "$HOME/.agents/skills/$6/SKILL.md"\n'
        )
        npx.chmod(0o755)

        result = self.run_cli(
            repo,
            home,
            "install-missing",
            path=f"{fakebin}:/usr/bin:/bin",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((home / "attempts").read_text().splitlines(), ["alpha", "beta", "gamma"])
        self.assertTrue((home / ".agents" / "skills" / "gamma" / "SKILL.md").is_file())
        self.assertIn("failed to install 1 skill: beta", result.stderr)

    def test_install_missing_rejects_option_like_catalog_source(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        fakebin = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(fakebin))
        entry = self.skill_entry("unsafe")
        entry["source"] = "--all"
        self.write_catalog(repo, {"unsafe": entry})
        npx = fakebin / "npx"
        npx.write_text('#!/usr/bin/env bash\n: > "$HOME/npx-called"\n')
        npx.chmod(0o755)

        result = self.run_cli(
            repo,
            home,
            "install-missing",
            path=f"{fakebin}:/usr/bin:/bin",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("broken catalog entry source starts with '-': unsafe", result.stderr)
        self.assertFalse((home / "npx-called").exists())

    def test_node_resolution_uses_documented_fallback_order(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        path_bin = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(path_bin))
        nvm_bin = home / "custom-nvm" / "bin" / "npx"
        nvm = home / ".nvm" / "versions" / "node" / "v24" / "bin" / "npx"
        mise = (
            home
            / ".local"
            / "share"
            / "mise"
            / "installs"
            / "node"
            / "23"
            / "bin"
            / "npx"
        )
        asdf = home / ".asdf" / "installs" / "nodejs" / "22" / "bin" / "npx"
        bun = home / ".bun" / "bin" / "npx"
        brew = home / "homebrew" / "bin" / "npx"
        path_npx = path_bin / "npx"
        candidates = (path_npx, nvm_bin, nvm, mise, asdf, bun, brew)
        for candidate in candidates:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text("#!/bin/sh\n")
            candidate.chmod(0o755)
            node = candidate.with_name("node")
            node.write_text("#!/bin/sh\n")
            node.chmod(0o755)

        overrides = {
            "NVM_BIN": str(nvm_bin.parent),
            "HOMEBREW_PREFIX": str(brew.parent.parent),
        }
        for index, expected in enumerate(candidates):
            with self.subTest(expected=expected):
                result = self.run_cli(
                    repo,
                    home,
                    "schedule",
                    path=str(path_bin),
                    env_overrides=overrides,
                )
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                cron = result.stdout.splitlines()[-1]
                scheduled_path = shlex.split(cron)[5].removeprefix("PATH=")
                self.assertEqual(
                    scheduled_path.split(os.pathsep)[0], str(expected.parent)
                )
            expected.unlink()
            expected.with_name("node").unlink()
            if index == 1:
                overrides.pop("NVM_BIN")

        linuxbrew = home / ".linuxbrew" / "bin" / "npx"
        linuxbrew.parent.mkdir(parents=True)
        linuxbrew.write_text("#!/bin/sh\n")
        linuxbrew.chmod(0o755)
        linuxbrew.with_name("node").write_text("#!/bin/sh\n")
        linuxbrew.with_name("node").chmod(0o755)
        result = self.run_cli(repo, home, "schedule", path=str(path_bin))

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        cron = result.stdout.splitlines()[-1]
        scheduled_path = shlex.split(cron)[5].removeprefix("PATH=")
        self.assertEqual(scheduled_path.split(os.pathsep)[0], str(linuxbrew.parent))

    def test_schedule_staggers_minute_by_hostname(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        npx = home / ".linuxbrew" / "bin" / "npx"
        npx.parent.mkdir(parents=True)
        npx.write_text("#!/bin/sh\n")
        npx.chmod(0o755)
        npx.with_name("node").write_text("#!/bin/sh\n")
        npx.with_name("node").chmod(0o755)
        expected = int.from_bytes(
            hashlib.sha256(socket.gethostname().encode()).digest()[:8], "big"
        ) % 60

        result = self.run_cli(repo, home, "schedule", path="/usr/bin:/bin")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(
            f"<key>Minute</key>\n    <integer>{expected}</integer>", result.stdout
        )
        self.assertTrue(result.stdout.splitlines()[-1].startswith(f"{expected} 9 "))

    def test_relative_skill_state_paths_are_resolved_before_export(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        fakebin = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(fakebin))
        for name in ("node", "npx"):
            executable = fakebin / name
            executable.write_text("#!/bin/sh\n")
            executable.chmod(0o755)
        overrides = {
            "SHARED_SKILLS": "relative/skills",
            "SKILLS_LOCK_FILE": "relative/state/lock.json",
        }
        expected_shared = (repo / "relative/skills").resolve()
        expected_lock = (repo / "relative/state/lock.json").resolve()

        shared = self.run_cli(repo, home, "resolve-shared", path=str(fakebin), env_overrides=overrides)
        lock = self.run_cli(repo, home, "resolve-lock", path=str(fakebin), env_overrides=overrides)
        schedule = self.run_cli(repo, home, "schedule", path=str(fakebin), env_overrides=overrides)

        self.assertEqual(shared.stdout.strip(), str(expected_shared))
        self.assertEqual(lock.stdout.strip(), str(expected_lock))
        self.assertIn(str(expected_shared), schedule.stdout)
        self.assertIn(str(expected_lock), schedule.stdout)

    def test_relative_xdg_state_home_uses_one_resolved_path(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        fakebin = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(fakebin))
        for name in ("node", "npx"):
            executable = fakebin / name
            executable.write_text("#!/bin/sh\n")
            executable.chmod(0o755)
        expected_xdg = (repo / "relative-state").resolve()
        overrides = {
            "XDG_STATE_HOME": "relative-state",
            "SKILLS_LOCK_FILE": "relative-config/lock.json",
        }
        expected_lock = (repo / "relative-config/lock.json").resolve()

        lock = self.run_cli(repo, home, "resolve-lock", path=str(fakebin), env_overrides=overrides)
        schedule = self.run_cli(repo, home, "schedule", path=str(fakebin), env_overrides=overrides)
        prepared = self.run_cli(repo, home, "prepare-state", path=str(fakebin), env_overrides=overrides)

        self.assertEqual(lock.stdout.strip(), str(expected_lock))
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertIn(f"XDG_STATE_HOME={expected_xdg}", schedule.stdout)
        self.assertNotIn("XDG_STATE_HOME=relative-state", schedule.stdout)
        self.assertEqual(
            (expected_xdg / "skills/.skill-lock.json").resolve(strict=False),
            expected_lock,
        )

    def test_node_resolution_sorts_manager_versions_numerically(self) -> None:
        _, home = self.make_home()
        repo = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(repo))
        managers = (
            (home / ".nvm" / "versions" / "node", "v9.0.0", "v22.15.0"),
            (home / ".local" / "share" / "mise" / "installs" / "node", "9.0.0", "22.15.0"),
            (home / ".asdf" / "installs" / "nodejs", "9.0.0", "22.15.0"),
        )
        for root, old_version, new_version in managers:
            with self.subTest(root=root):
                for version in (old_version, new_version):
                    npx = root / version / "bin" / "npx"
                    npx.parent.mkdir(parents=True)
                    npx.write_text("#!/bin/sh\n")
                    npx.chmod(0o755)

                result = self.run_cli(
                    repo,
                    home,
                    "resolve-npx",
                    path="/missing",
                )

                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual(
                    result.stdout.strip(), str(root / new_version / "bin" / "npx")
                )
            shutil.rmtree(root)

    def test_skills_update_uses_fallback_npx(self) -> None:
        _, home = self.make_home()
        shared = home / ".agents" / "skills"
        catalog = json.loads((ROOT / "skills-catalog.json").read_text())["skills"]
        for name in catalog:
            self.create_skill(home, name)
        subprocess.run(
            [
                "/usr/bin/python3",
                str(ROOT / "scripts" / "skill_metadata.py"),
                "apply",
                str(shared),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        npx = home / ".linuxbrew" / "bin" / "npx"
        npx.parent.mkdir(parents=True)
        npx.write_text(
            '#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" > "$HOME/npx.args"\n'
        )
        npx.chmod(0o755)
        npx.with_name("node").write_text("#!/bin/sh\n")
        npx.with_name("node").chmod(0o755)
        fakebin = home / "bin"
        fakebin.mkdir()
        for name in ("bash", "chmod", "dirname", "mkdir", "python3", "readlink"):
            source = pathlib.Path("/usr/bin") / name
            if not source.exists():
                source = pathlib.Path("/bin") / name
            (fakebin / name).symlink_to(source)
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["PATH"] = str(fakebin)
        for name in ("NVM_BIN", "MISE_DATA_DIR", "ASDF_DATA_DIR", "HOMEBREW_PREFIX"):
            env.pop(name, None)

        result = subprocess.run(
            [str(ROOT / "bin" / "skills-update")],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((home / "npx.args").read_text(), "--yes skills update -g\n")


if __name__ == "__main__":
    unittest.main()
