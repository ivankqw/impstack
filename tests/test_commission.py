from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
COMMISSION = ROOT / "bin" / "commission"
CONTRACT = ROOT / "commission.contract.json"


class CommissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.sandbox = pathlib.Path(self.tempdir.name)
        self.home = self.sandbox / "home"
        self.repo = self.sandbox / "repo"
        self.fakebin = self.sandbox / "bin"
        self.home.mkdir()
        self.repo.mkdir()
        self.fakebin.mkdir()
        (self.repo / "bin").mkdir()
        shutil.copy(CONTRACT, self.repo / CONTRACT.name)
        self.write_fake_commands()

    def write_executable(self, path: pathlib.Path, body: str) -> None:
        path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body)
        path.chmod(0o755)

    def write_fake_commands(self) -> None:
        common = textwrap.dedent(
            """\
            id="${COMMISSION_ASSERTION_ID:-}"
            if [[ "${FAIL_ASSERTION:-}" == "$id" ]]; then
              printf '%s\\n' "${FAILURE_SENTINEL:-forced failure for $id}" >&2
              exit 41
            fi
            case ",${FAIL_ASSERTIONS:-}," in
              *,$id,*) printf '%s\\n' "${FAILURE_SENTINEL:-forced failure for $id}" >&2; exit 41 ;;
            esac
            """
        )
        self.write_executable(
            self.repo / "install.sh",
            common
            + '# shared path authority: "$AC/bin/skills-sync" resolve-shared\n'
            + "printf '%s\\n' \"$*\"\n",
        )
        (self.repo / "bin" / "skills-update").write_text(
            '# shared path authority: "$AC/bin/skills-sync" resolve-shared\n'
        )
        self.write_executable(
            self.repo / "bin" / "skills-sync",
            common
            + textwrap.dedent(
                """\
                case "${1:-}" in
                  resolve-shared) printf '%s\\n' "$SHARED_SKILLS" ;;
                  resolve-node) command -v node ;;
                  resolve-npx) command -v npx ;;
                  check) printf 'catalog valid\\n' ;;
                  *) exit 2 ;;
                esac
                """
            ),
        )
        for name in ("node", "npx", "bun"):
            self.write_executable(
                self.fakebin / name,
                common + f"printf '{name} 1.2.3\\n'\n",
            )
        for name in ("claude", "codex", "opencode"):
            self.write_executable(
                self.fakebin / name,
                common
                + textwrap.dedent(
                    f"""\
                    case "${{1:-}}" in
                      --version) printf '{name} 1.2.3\\n' ;;
                      auth|login) printf 'authenticated\\n' ;;
                      mcp)
                        if [[ "${{2:-}}" == "list" ]]; then
                          printf 'context7 exa linear-server executor\\n'
                        else
                          printf '%s registered\\n' "${{3:-}}"
                        fi
                        ;;
                      *) printf 'LOADED\\n' ;;
                    esac
                    """
                ),
            )

        shared = self.home / ".agents" / "skills"
        template = shared / "wizard" / "template.sh"
        template.parent.mkdir(parents=True)
        template.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            "TOTAL_STAGES=0\n"
            "banner(){ :; }\nstage(){ :; }\nsay(){ :; }\nstep(){ :; }\n"
            "open_url(){ :; }\npause(){ :; }\nconfirm(){ return 0; }\n"
            "ask_secret(){ printf -v \"$1\" value; }\n"
            "write_env(){ :; }\nfinish(){ :; }\n"
            "# STAGES: author this section. One stage() per step the human takes.\n"
            "TOTAL_STAGES=1\nbanner \"example\"\nstage \"example\"\nfinish\n"
        )

    def environment(self, **overrides: str) -> dict[str, str]:
        env = {
            "HOME": str(self.home),
            "PATH": str(self.fakebin) + os.pathsep + "/usr/bin" + os.pathsep + "/bin",
            "SHARED_SKILLS": str(self.home / ".agents" / "skills"),
            "EXECUTOR_MCP_URL": "set-for-test-but-never-print",
            "SHELL": "/bin/fakesh",
        }
        env.update(overrides)
        return env

    def run_commission(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(COMMISSION), *args, "--repo", str(self.repo), "--home", str(self.home)],
            cwd=self.repo,
            env=env or self.environment(),
            text=True,
            capture_output=True,
            check=False,
        )

    def assertion_ids(self) -> list[str]:
        contract = json.loads(CONTRACT.read_text())
        return [item["id"] for item in contract["assertions"]]

    def test_every_assertion_passes_and_both_reports_name_each_assertion(self) -> None:
        text_result = self.run_commission("check", "--format", "text")
        json_result = self.run_commission("check", "--format", "json")

        self.assertEqual(text_result.returncode, 0, text_result.stderr + text_result.stdout)
        self.assertEqual(json_result.returncode, 0, json_result.stderr + json_result.stdout)
        report = json.loads(json_result.stdout)
        self.assertEqual([item["id"] for item in report["assertions"]], self.assertion_ids())
        self.assertTrue(all(item["status"] == "pass" for item in report["assertions"]))
        for assertion_id in self.assertion_ids():
            self.assertIn(assertion_id, text_result.stdout)

    def test_each_assertion_fails_in_turn_and_names_its_id(self) -> None:
        for assertion_id in self.assertion_ids():
            with self.subTest(assertion_id=assertion_id):
                result = self.run_commission(
                    "check",
                    "--format",
                    "text",
                    env=self.environment(FAIL_ASSERTION=assertion_id),
                )
                self.assertEqual(result.returncode, 1)
                matching = [line for line in result.stdout.splitlines() if assertion_id in line]
                self.assertTrue(matching, result.stdout)
                self.assertTrue(any("fail" in line for line in matching), result.stdout)

    def test_missing_harness_is_not_applicable(self) -> None:
        (self.fakebin / "opencode").unlink()

        result = self.run_commission("check", "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        statuses = {
            item["id"]: item["status"]
            for item in json.loads(result.stdout)["assertions"]
        }
        self.assertEqual(statuses["harness.opencode.auth"], "not-applicable")
        self.assertEqual(statuses["harness.opencode.canary"], "not-applicable")
        self.assertEqual(statuses["mcp.context7.opencode"], "not-applicable")

    def test_missing_harness_does_not_generate_its_login_stage(self) -> None:
        (self.fakebin / "opencode").unlink()
        record = self.sandbox / "record.md"
        wizard = self.sandbox / "wizard.sh"

        result = self.run_commission(
            "probe", "--record", str(record), "--wizard", str(wizard)
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotIn('stage "OpenCode login"', wizard.read_text())

    def test_missing_executor_url_generates_actionable_connection_stage(self) -> None:
        environment = self.environment()
        environment.pop("EXECUTOR_MCP_URL")
        record = self.sandbox / "record.md"
        wizard = self.sandbox / "wizard.sh"

        result = self.run_commission(
            "probe", "--record", str(record), "--wizard", str(wizard), env=environment
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        wizard_text = wizard.read_text()
        self.assertEqual(wizard_text.count('stage "Executor connection"'), 1)
        self.assertIn('ask_secret EXECUTOR_MCP_URL', wizard_text)
        self.assertIn('open_url "$EXECUTOR_MCP_URL"', wizard_text)
        self.assertIn("complete the browser sign-in", wizard_text)

    def test_context7_failures_generate_one_secret_input_stage(self) -> None:
        record = self.sandbox / "record.md"
        wizard = self.sandbox / "wizard.sh"
        failures = ",".join(
            (
                "mcp.context7.claude",
                "mcp.context7.codex",
                "mcp.context7.opencode",
            )
        )

        result = self.run_commission(
            "probe",
            "--record",
            str(record),
            "--wizard",
            str(wizard),
            env=self.environment(FAIL_ASSERTIONS=failures),
        )

        self.assertEqual(result.returncode, 1)
        wizard_text = wizard.read_text()
        self.assertEqual(wizard_text.count('stage "Context7 token"'), 1)
        self.assertIn('open_url "https://context7.com/dashboard"', wizard_text)
        self.assertIn('ask_secret CONTEXT7_API_KEY', wizard_text)
        self.assertIn('ENV_FILE="$HOME/.config/impstack/env"', wizard_text)
        self.assertIn("source $ENV_FILE", wizard_text)
        self.assertIn("./install.sh mcp", wizard_text)

    def test_contract_declares_actionable_statuses(self) -> None:
        contract = json.loads(CONTRACT.read_text())

        for assertion in contract["assertions"]:
            statuses = assertion["remediation"].get("statuses")
            self.assertIsInstance(statuses, list, assertion["id"])
            self.assertTrue(statuses, assertion["id"])

    def test_probe_writes_complete_record_and_manual_only_wizard(self) -> None:
        record = self.sandbox / "machine-record" / "SKILL.md"
        wizard = self.sandbox / "commission-wizard.sh"
        result = self.run_commission(
            "probe",
            "--record",
            str(record),
            "--wizard",
            str(wizard),
            env=self.environment(FAIL_ASSERTION="harness.codex.auth"),
        )

        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        content = record.read_text()
        self.assertRegex(content, r"^---\nname: machine-[a-z0-9-]+\n")
        self.assertIn("setup, troubleshooting, or provisioning", content)
        for heading in (
            "## Identity",
            "## Runtime",
            "## Harnesses",
            "## Connections",
            "## Contract",
            "## Remediation",
        ):
            self.assertIn(heading, content)
        self.assertNotIn("TODO", content)
        self.assertNotIn("PLACEHOLDER", content)
        wizard_text = wizard.read_text()
        self.assertIn('stage "Codex login"', wizard_text)
        self.assertNotIn('stage "Claude login"', wizard_text)
        self.assertTrue(os.access(wizard, os.X_OK))

    def test_executor_url_value_never_appears_in_output_or_record(self) -> None:
        secret_url = "https://secret-tenant.invalid/mcp"
        record = self.sandbox / "record.md"
        result = self.run_commission(
            "probe",
            "--record",
            str(record),
            env=self.environment(EXECUTOR_MCP_URL=secret_url),
        )

        combined = result.stdout + result.stderr + record.read_text()
        self.assertNotIn(secret_url, combined)

    def test_arbitrary_command_output_is_absent_from_all_reports(self) -> None:
        sentinel = "s3nt1nel-private-material-947"
        environment = self.environment(
            FAIL_ASSERTION="install.list", FAILURE_SENTINEL=sentinel
        )
        text_result = self.run_commission("check", "--format", "text", env=environment)
        json_result = self.run_commission("check", "--format", "json", env=environment)
        record = self.sandbox / "record.md"
        probe_result = self.run_commission(
            "probe", "--record", str(record), env=environment
        )

        self.assertNotIn(sentinel, text_result.stdout + text_result.stderr)
        self.assertNotIn(sentinel, json_result.stdout + json_result.stderr)
        self.assertNotIn(sentinel, probe_result.stdout + probe_result.stderr)
        self.assertNotIn(sentinel, record.read_text())
        assertion = next(
            item
            for item in json.loads(json_result.stdout)["assertions"]
            if item["id"] == "install.list"
        )
        self.assertEqual(
            set(assertion),
            {"id", "status", "message", "command", "exit_code", "remediation"},
        )

    def test_probe_is_byte_idempotent(self) -> None:
        record = self.sandbox / "record.md"
        wizard = self.sandbox / "wizard.sh"
        arguments = ("probe", "--record", str(record), "--wizard", str(wizard))

        first = self.run_commission(*arguments)
        first_record = record.read_bytes()
        first_wizard = wizard.read_bytes()
        second = self.run_commission(*arguments)

        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(record.read_bytes(), first_record)
        self.assertEqual(wizard.read_bytes(), first_wizard)


if __name__ == "__main__":
    unittest.main()
