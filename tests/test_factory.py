from __future__ import annotations

import copy
import json
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
FACTORY = ROOT / "bin" / "factory"
CONFIG_PATH = ROOT / "configs" / "factory" / "reviewed-change.json"
BRIEF_PATH = ROOT / "configs" / "factory" / "brief.json"
RESULT_PATH = ROOT / "configs" / "factory" / "result.json"
HOOK = ROOT / "hooks" / "review_reminder.py"


class FactoryCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.sandbox = pathlib.Path(self.tempdir.name)

    def run_factory(self, *args: str, cwd: pathlib.Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(FACTORY), *args],
            cwd=cwd or ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def load_json(self, path: pathlib.Path) -> dict[str, object]:
        return json.loads(path.read_text())

    def write_json(self, name: str, value: object) -> pathlib.Path:
        path = self.sandbox / name
        path.write_text(json.dumps(value, indent=2) + "\n")
        return path

    def test_example_config_and_contracts_validate(self) -> None:
        config = self.run_factory("validate", str(CONFIG_PATH), "--format", "json")
        brief = self.run_factory(
            "validate-brief",
            str(BRIEF_PATH),
            "--config",
            str(CONFIG_PATH),
            "--format",
            "json",
        )
        result = self.run_factory(
            "validate-result",
            str(RESULT_PATH),
            "--brief",
            str(BRIEF_PATH),
            "--config",
            str(CONFIG_PATH),
            "--format",
            "json",
        )

        for completed in (config, brief, result):
            self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
            self.assertTrue(json.loads(completed.stdout)["valid"])

    def test_same_recipe_allows_implementation_profile_substitution(self) -> None:
        original = self.run_factory(
            "plan", str(CONFIG_PATH), "--assignment", "native"
        )
        alternate = self.run_factory(
            "plan",
            str(CONFIG_PATH),
            "--assignment",
            "native-alternate-implementer",
        )

        self.assertEqual(original.returncode, 0, original.stderr)
        self.assertEqual(alternate.returncode, 0, alternate.stderr)
        first = json.loads(original.stdout)
        second = json.loads(alternate.stdout)
        self.assertEqual(first["recipe"], second["recipe"])
        self.assertEqual(first["steps"], second["steps"])
        self.assertEqual(first["invariants"], second["invariants"])
        self.assertEqual(first["roles"]["orchestrator"], second["roles"]["orchestrator"])
        self.assertEqual(first["roles"]["reviewer"], second["roles"]["reviewer"])
        self.assertNotEqual(first["roles"]["implementer"], second["roles"]["implementer"])

    def test_plans_describe_each_transport_without_commands(self) -> None:
        expected = {
            "native": ("native-codex-app", "caller-dispatch"),
            "herdr": ("herdr-cli", "herdr-handoff"),
            "hybrid": ("hybrid", None),
        }
        for assignment, (transport, action) in expected.items():
            with self.subTest(assignment=assignment):
                completed = self.run_factory(
                    "plan", str(CONFIG_PATH), "--assignment", assignment
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                plan = json.loads(completed.stdout)
                self.assertEqual(plan["transport"], transport)
                self.assertEqual(plan["modules"]["installation"], "none")
                self.assertTrue(all(item["command"] is None for item in plan["handoffs"]))
                if action is not None:
                    self.assertTrue(all(item["action"] == action for item in plan["handoffs"]))

    def test_unknown_role_reference_fails(self) -> None:
        config = self.load_json(CONFIG_PATH)
        config["assignments"]["native"]["roles"]["implementer"] = "missing-profile"
        path = self.write_json("bad-role.json", config)

        completed = self.run_factory("validate", str(path), "--format", "json")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("unknown profile", json.loads(completed.stdout)["error"])

    def test_invalid_transport_harness_pair_fails(self) -> None:
        config = self.load_json(CONFIG_PATH)
        config["assignments"]["native"]["roles"]["implementer"] = "herdr-implementer"
        path = self.write_json("bad-transport.json", config)

        completed = self.run_factory("validate", str(path))

        self.assertEqual(completed.returncode, 2)
        self.assertIn("requires native-codex-app", completed.stderr)

    def test_reviewer_identity_collision_fails_through_profile_aliases(self) -> None:
        config = self.load_json(CONFIG_PATH)
        config["profiles"]["reviewer-alias"] = copy.deepcopy(
            config["profiles"]["native-implementer"]
        )
        config["profiles"]["reviewer-alias"]["options"]["fresh_context"] = True
        config["assignments"]["native"]["roles"]["reviewer"] = "reviewer-alias"
        path = self.write_json("same-identity.json", config)

        completed = self.run_factory("validate", str(path))

        self.assertEqual(completed.returncode, 2)
        self.assertIn("same provider/model identity", completed.stderr)

    def test_boolean_version_and_cross_vendor_provider_collision_fail(self) -> None:
        config = self.load_json(CONFIG_PATH)
        config["version"] = True
        bool_version = self.run_factory("validate", str(self.write_json("bool-version.json", config)))
        self.assertEqual(bool_version.returncode, 2)
        self.assertIn("config.version must be 1", bool_version.stderr)

        config = self.load_json(CONFIG_PATH)
        config["profiles"]["caller-reviewer"]["options"]["cross_vendor"] = True
        cross_vendor = self.run_factory(
            "validate", str(self.write_json("cross-vendor.json", config))
        )
        self.assertEqual(cross_vendor.returncode, 2)
        self.assertIn("requires a different provider", cross_vendor.stderr)

    def test_profile_identity_rejects_surrounding_whitespace(self) -> None:
        for field in ("provider", "model"):
            with self.subTest(field=field):
                config = self.load_json(CONFIG_PATH)
                implementer = config["profiles"]["native-implementer"]
                reviewer = config["profiles"]["caller-reviewer"]
                reviewer.update(provider=implementer["provider"], model=implementer["model"])
                reviewer[field] += " "
                completed = self.run_factory(
                    "validate", str(self.write_json("whitespace-identity.json", config))
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIn("must not have surrounding whitespace", completed.stderr)

    def test_success_rejects_whitespace_commit(self) -> None:
        brief = self.load_json(BRIEF_PATH)
        result = self.load_json(RESULT_PATH)
        result.update(
            status="success",
            actual_commit=" \t",
            unresolved_work=[],
            evidence=[
                {"command": check["command"], "exit_code": 0, "output": "test output"}
                for check in brief["checks"]
            ],
        )
        completed = self.run_factory(
            "validate-result",
            str(self.write_json("whitespace-commit.json", result)),
            "--brief", str(BRIEF_PATH),
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("actual_commit must be a non-empty string", completed.stderr)

    def test_profiles_and_hybrid_topology_use_declared_transports(self) -> None:
        config = self.load_json(CONFIG_PATH)
        config["profiles"]["caller-planner"]["harness"] = "codex-cli"
        invalid_profile = self.run_factory(
            "validate", str(self.write_json("invalid-native-profile.json", config))
        )
        self.assertEqual(invalid_profile.returncode, 2)
        self.assertIn("requires harness codex-app", invalid_profile.stderr)

        config = self.load_json(CONFIG_PATH)
        config["assignments"]["hybrid"]["roles"]["reviewer"] = "herdr-reviewer"
        valid_hybrid = self.run_factory(
            "validate", str(self.write_json("hybrid-herdr-reviewer.json", config))
        )
        self.assertEqual(valid_hybrid.returncode, 0, valid_hybrid.stderr)

        config["assignments"]["hybrid"]["roles"]["implementer"] = "native-implementer"
        config["assignments"]["hybrid"]["roles"]["reviewer"] = "caller-reviewer"
        invalid_hybrid = self.run_factory(
            "validate", str(self.write_json("invalid-hybrid.json", config))
        )
        self.assertEqual(invalid_hybrid.returncode, 2)
        self.assertIn("must include native-codex-app and herdr-cli", invalid_hybrid.stderr)

    def test_unknown_key_fails_at_config_boundary(self) -> None:
        config = self.load_json(CONFIG_PATH)
        config["assignments"]["native"]["typo"] = True
        path = self.write_json("unknown-key.json", config)

        completed = self.run_factory("validate", str(path), "--format", "json")

        self.assertEqual(completed.returncode, 2)
        self.assertIn("unknown key", json.loads(completed.stdout)["error"])

    def test_idle_result_and_unbound_result_fail(self) -> None:
        result = self.load_json(RESULT_PATH)
        result["status"] = "idle"
        idle_path = self.write_json("idle-result.json", result)
        idle = self.run_factory("validate-result", str(idle_path))
        self.assertEqual(idle.returncode, 2)
        self.assertIn("status is invalid", idle.stderr)

        result["status"] = "incomplete"
        result["assignment"] = "herdr"
        unbound_path = self.write_json("unbound-result.json", result)
        unbound = self.run_factory(
            "validate-result",
            str(unbound_path),
            "--brief",
            str(BRIEF_PATH),
            "--config",
            str(CONFIG_PATH),
        )
        self.assertEqual(unbound.returncode, 2)
        self.assertIn("does not match brief.assignment", unbound.stderr)

    def test_success_requires_evidence_and_allows_a_new_commit(self) -> None:
        result = self.load_json(RESULT_PATH)
        result.update(
            {
                "status": "success",
                "actual_commit": "new-commit-created-by-implementer",
                "unresolved_work": [],
                "evidence": [
                    {
                        "command": [
                            "python3",
                            "-m",
                            "unittest",
                            "discover",
                            "-s",
                            "tests",
                            "-p",
                            "test_factory.py",
                        ],
                        "exit_code": 0,
                        "output": "all tests passed",
                    }
                ],
            }
        )
        path = self.write_json("success-result.json", result)
        completed = self.run_factory(
            "validate-result",
            str(path),
            "--brief",
            str(BRIEF_PATH),
            "--config",
            str(CONFIG_PATH),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_plan_with_brief_does_not_write_files(self) -> None:
        config = self.sandbox / "config.json"
        config.write_text(CONFIG_PATH.read_text())
        before = sorted(path.name for path in self.sandbox.iterdir())

        completed = self.run_factory(
            "plan",
            str(config),
            "--assignment",
            "hybrid",
            "--brief",
            str(BRIEF_PATH),
            cwd=self.sandbox,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(before, sorted(path.name for path in self.sandbox.iterdir()))

    def test_symlinked_bin_wrapper_resolves_repository_root(self) -> None:
        link = self.sandbox / "factory"
        link.symlink_to(FACTORY)

        completed = subprocess.run(
            [str(link), "validate", str(CONFIG_PATH)],
            cwd=self.sandbox,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_review_reminder_uses_selected_profile_language(self) -> None:
        event = {"tool_name": "Bash", "tool_input": {"command": "git push origin x"}}
        completed = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "FACTORY_REVIEWER_PROFILE": "caller-reviewer"},
        )

        self.assertEqual(completed.returncode, 0)
        output = json.loads(completed.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("selected reviewer profile", output)
        self.assertIn("active preset reviewer", output)
        self.assertNotIn("Sonnet", output)


if __name__ == "__main__":
    unittest.main()
