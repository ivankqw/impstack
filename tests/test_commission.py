from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest

from scripts import commission as commission_module


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
            case ",${ABSENT_ASSERTIONS:-}," in
              *,$id,*) export COMMISSION_FAKE_ABSENT=true ;;
            esac
            if [[ "${CANARY_ASSERTION_ID:-}" == "$id" ]]; then
              printf '%s\n' "${CANARY_RESPONSE:-}"
              exit 0
            fi
            """
        )
        self.write_executable(
            self.repo / "install.sh",
            common
            + 'AC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
            + '"$AC/bin/skills-sync" resolve-shared >/dev/null\n'
            + "printf '%s\\n' \"$*\"\n",
        )
        self.write_executable(
            self.repo / "bin" / "skills-update",
            'AC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
            + '"$AC/bin/skills-sync" resolve-shared >/dev/null\n',
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
        for name in ("node", "npx", "npm", "bun"):
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
                        if [[ "${{COMMISSION_FAKE_ABSENT:-}}" == true && "{name}" == codex ]]; then
                          printf "Error: No MCP server named '%s' found.\n" "${{3:-}}" >&2
                          exit 1
                        fi
                        if [[ "${{2:-}}" == "list" ]]; then
                          if [[ "${{COMMISSION_FAKE_ABSENT:-}}" == true ]]; then
                            case "$id" in
                              mcp.context7.opencode) printf 'exa linear-server executor\\n' ;;
                              mcp.exa.opencode) printf 'context7 linear-server executor\\n' ;;
                              mcp.linear-server.opencode) printf 'context7 exa executor\\n' ;;
                              mcp.executor.opencode) printf 'context7 exa linear-server\\n' ;;
                            esac
                          else
                            printf 'context7 exa linear-server executor\\n'
                          fi
                        else
                          printf '%s registered\\n' "${{3:-}}"
                        fi
                        ;;
                      *)
                        if [[ "$PWD" == "$IMPSTACK_DIR" || "$PWD" == "$IMPSTACK_DIR/"* ]]; then
                          response=MISSING
                        else
                          response=LOADED
                        fi
                        if [[ "{name}" == opencode && "$*" == *"--format json"* ]]; then
                          printf '{{"type":"text","part":{{"type":"text","text":"%s"}}}}\\n' "$response"
                        else
                          printf '%s\\n' "$response"
                        fi
                        ;;
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

    def applicable_failure_ids(self) -> list[str]:
        contract = json.loads(CONTRACT.read_text())
        return [
            item["id"]
            for item in contract["assertions"]
            if item.get("absent_registration", {}).get("status") != "not-applicable"
        ]

    def test_generated_machine_skill_is_ignored_by_real_skills_check(self) -> None:
        repo = self.sandbox / "skills-check-repo"
        repo.mkdir()
        (repo / "skills-catalog.json").write_text('{"skills": {}}\n')
        shutil.copy(ROOT / "skills-ignore.txt", repo / "skills-ignore.txt")
        check_home = self.sandbox / "skills-check-home"
        machine = check_home / ".agents" / "skills" / "machine-test-host"
        machine.mkdir(parents=True, exist_ok=True)
        (machine / "SKILL.md").write_text(
            "---\nname: machine-test-host\ndescription: Test machine.\n---\n"
        )
        environment = self.environment(
            HOME=str(check_home),
            SHARED_SKILLS=str(check_home / ".agents" / "skills"),
            IMPSTACK_DIR=str(repo),
        )

        result = subprocess.run(
            [str(ROOT / "bin" / "skills-sync"), "check"],
            cwd=repo,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        patterns = (ROOT / "skills-ignore.txt").read_text().splitlines()
        self.assertIn("lark-*", patterns)
        self.assertIn("machine-*", patterns)

    def test_harness_canaries_run_outside_the_repo(self) -> None:
        result = self.run_commission("check", "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        contract = json.loads(CONTRACT.read_text())
        canaries = [
            item for item in contract["assertions"] if item["id"].endswith(".canary")
        ]
        self.assertTrue(canaries)
        self.assertTrue(
            all(item.get("working_directory") == "outside-project" for item in canaries)
        )
        self.assertTrue(
            all(
                item.get("working_directory") == "repo"
                for item in contract["assertions"]
                if not item["id"].endswith(".canary")
            )
        )

    def test_rejected_outside_project_root_has_no_side_effect(self) -> None:
        cache = self.home / ".cache" / "impstack" / "commission"

        result = subprocess.run(
            [
                str(COMMISSION),
                "check",
                "--repo",
                str(self.home),
                "--home",
                str(self.home),
                "--contract",
                str(CONTRACT),
            ],
            cwd=self.repo,
            env=self.environment(),
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("outside-project directory must be outside", result.stderr)
        self.assertFalse(cache.exists())

    def test_ambiguous_canary_response_is_indeterminate(self) -> None:
        result = self.run_commission(
            "check",
            "--format",
            "json",
            env=self.environment(
                CANARY_ASSERTION_ID="harness.codex.canary",
                CANARY_RESPONSE=(
                    "My instructions do not contain that phrase, so the answer is not "
                    "LOADED; it is MISSING"
                ),
            ),
        )

        report = {
            item["id"]: item for item in json.loads(result.stdout)["assertions"]
        }
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["harness.codex.canary"]["status"], "indeterminate")
        self.assertEqual(
            report["harness.codex.canary"]["message"],
            "canary response was indeterminate",
        )

    def test_opencode_canary_reads_raw_json_text_events(self) -> None:
        self.write_executable(
            self.fakebin / "opencode",
            textwrap.dedent(
                """\
                if [[ "$*" == *"--format json"* ]]; then
                  printf '%s\n' '{"type":"text","part":{"type":"text","text":"LOADED"}}'
                else
                  printf 'decorated output: LOADED\n'
                fi
                """
            ),
        )
        assertion = next(
            item
            for item in commission_module.load_contract(CONTRACT)
            if item.assertion_id == "harness.opencode.canary"
        )
        outside = self.sandbox / "outside"
        outside.mkdir()
        context = commission_module.Context(
            self.repo, self.home, self.environment(), outside
        )

        report = commission_module.evaluate((assertion,), context)

        self.assertEqual(assertion.kind, "json-canary")
        self.assertEqual(assertion.command[0:4], ("opencode", "run", "--format", "json"))
        self.assertEqual(report.results[0].status, commission_module.Status.PASS)

    def test_contract_covers_each_declared_mcp_server_for_each_harness(self) -> None:
        contract = json.loads(CONTRACT.read_text())
        servers = json.loads((ROOT / "mcp" / "servers.json").read_text())["servers"]
        actual = {
            item["id"]
            for item in contract["assertions"]
            if item["id"].startswith("mcp.")
        }
        expected = {
            f"mcp.{server['name']}.{harness}"
            for server in servers
            for harness in ("claude", "codex", "opencode")
        }

        self.assertEqual(actual, expected)

    def test_every_assertion_passes_and_both_reports_name_each_assertion(self) -> None:
        text_result = self.run_commission("check", "--format", "text")
        json_result = self.run_commission("check", "--format", "json")

        self.assertEqual(text_result.returncode, 0, text_result.stderr + text_result.stdout)
        self.assertEqual(json_result.returncode, 0, json_result.stderr + json_result.stdout)
        report = json.loads(json_result.stdout)
        self.assertEqual([item["id"] for item in report["assertions"]], self.assertion_ids())
        self.assertTrue(all(item["status"] == "pass" for item in report["assertions"]))
        for assertion_id in self.applicable_failure_ids():
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
        self.assertNotIn('stage "Executor connection"', wizard.read_text())

    def test_unsupported_absent_mcp_is_not_applicable_with_reason(self) -> None:
        unsupported = (
            "mcp.context7.codex",
            "mcp.context7.opencode",
            "mcp.exa.opencode",
            "mcp.linear-server.opencode",
            "mcp.executor.opencode",
        )
        result = self.run_commission(
            "check",
            "--format",
            "json",
            env=self.environment(ABSENT_ASSERTIONS=",".join(unsupported)),
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        report = {
            item["id"]: item for item in json.loads(result.stdout)["assertions"]
        }
        for assertion_id in unsupported:
            self.assertEqual(report[assertion_id]["status"], "not-applicable")
            self.assertIn("install.sh cannot register", report[assertion_id]["message"])

    def test_generic_codex_failure_is_not_treated_as_missing_context7(self) -> None:
        self.write_executable(self.fakebin / "codex", "exit 1\n")

        result = self.run_commission("check", "--format", "json")

        report = {
            item["id"]: item for item in json.loads(result.stdout)["assertions"]
        }
        self.assertEqual(result.returncode, 1)
        self.assertEqual(report["mcp.context7.codex"]["status"], "fail")

    def test_unknown_wizard_stage_id_fails_contract_loading(self) -> None:
        contract = json.loads(CONTRACT.read_text())
        contract["assertions"][0]["remediation"] = {
            "kind": "wizard",
            "stage_id": "unknown-stage",
            "stage": "Unknown stage",
            "statuses": ["fail"],
        }
        path = self.sandbox / "unknown-stage.contract.json"
        path.write_text(json.dumps(contract))

        result = self.run_commission(
            "check", "--format", "text", "--contract", str(path)
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid remediation", result.stderr)

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
        self.assertIn('open_url "https://executor.sh"', wizard_text)
        self.assertNotIn('open_url "$EXECUTOR_MCP_URL"', wizard_text)
        self.assertIn("copy the tenant MCP URL", wizard_text)

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

    def test_missing_wizard_template_names_the_dependency_before_writes(self) -> None:
        template = self.home / ".agents" / "skills" / "wizard" / "template.sh"
        template.unlink()
        record = self.sandbox / "record.md"
        wizard = self.sandbox / "wizard.sh"
        record.write_text("keep record\n")
        wizard.write_text("keep wizard\n")

        result = self.run_commission(
            "probe", "--record", str(record), "--wizard", str(wizard)
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn(f"wizard template is missing: {template}", result.stderr)
        self.assertIn("install the wizard skill", result.stderr)
        self.assertEqual(record.read_text(), "keep record\n")
        self.assertEqual(wizard.read_text(), "keep wizard\n")

    def test_incompatible_wizard_template_names_the_missing_helper(self) -> None:
        template = self.home / ".agents" / "skills" / "wizard" / "template.sh"
        template.write_text(
            template.read_text().replace(
                'ask_secret(){ printf -v "$1" value; }\n', ""
            )
        )
        record = self.sandbox / "record.md"
        wizard = self.sandbox / "wizard.sh"

        result = self.run_commission(
            "probe", "--record", str(record), "--wizard", str(wizard)
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("wizard template is missing helper: ask_secret", result.stderr)
        self.assertFalse(record.exists())
        self.assertFalse(wizard.exists())

    def test_contract_declares_actionable_statuses(self) -> None:
        contract = json.loads(CONTRACT.read_text())

        for assertion in contract["assertions"]:
            statuses = assertion["remediation"].get("statuses")
            self.assertIsInstance(statuses, list, assertion["id"])
            self.assertTrue(statuses, assertion["id"])
            self.assertIn(assertion.get("working_directory"), ("repo", "outside-project"))
            if assertion["remediation"]["kind"] == "wizard":
                self.assertRegex(
                    assertion["remediation"].get("stage_id", ""),
                    r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
                )

    def test_contract_rejects_missing_positive_signals(self) -> None:
        contract = json.loads(CONTRACT.read_text())
        canary = next(
            item for item in contract["assertions"]
            if item["id"] == "harness.codex.canary"
        )
        canary["expectation"].pop("stdout_equals")
        canary_path = self.sandbox / "canary.contract.json"
        canary_path.write_text(json.dumps(contract))

        canary_result = self.run_commission(
            "check", "--format", "text", "--contract", str(canary_path)
        )

        contract = json.loads(CONTRACT.read_text())
        context7 = next(
            item for item in contract["assertions"]
            if item["id"] == "mcp.context7.codex"
        )
        context7["absent_registration"]["stderr_contains"] = ""
        context7_path = self.sandbox / "context7.contract.json"
        context7_path.write_text(json.dumps(contract))

        context7_result = self.run_commission(
            "check", "--format", "text", "--contract", str(context7_path)
        )

        contract = json.loads(CONTRACT.read_text())
        context7 = next(
            item for item in contract["assertions"]
            if item["id"] == "mcp.context7.codex"
        )
        context7["absent_registration"]["reason"] = ""
        empty_reason_path = self.sandbox / "empty-reason.contract.json"
        empty_reason_path.write_text(json.dumps(contract))

        empty_reason_result = self.run_commission(
            "check", "--format", "text", "--contract", str(empty_reason_path)
        )

        self.assertEqual(canary_result.returncode, 2)
        self.assertIn("invalid assertion", canary_result.stderr)
        self.assertEqual(context7_result.returncode, 2)
        self.assertIn("invalid absent registration", context7_result.stderr)
        self.assertEqual(empty_reason_result.returncode, 2)
        self.assertIn("invalid absent registration", empty_reason_result.stderr)

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
        self.assertNotIn(";", content)
        self.assertIn("Package manager: `", content)
        self.assertIn("Version: `1.2.3`", content)
        wizard_text = wizard.read_text()
        self.assertIn('stage "Codex login"', wizard_text)
        self.assertNotIn('stage "Claude login"', wizard_text)
        self.assertTrue(os.access(wizard, os.X_OK))

    def test_probe_chooses_record_path_with_its_machine_name(self) -> None:
        result = self.run_commission("probe")

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        prefix = "record wrote "
        record_line = next(
            line for line in result.stdout.splitlines() if line.startswith(prefix)
        )
        record = pathlib.Path(record_line.removeprefix(prefix))
        skill_name = next(
            line.removeprefix("name: ")
            for line in record.read_text().splitlines()
            if line.startswith("name: ")
        )
        self.assertEqual(record.parent.name, skill_name)
        self.assertEqual(record.name, "SKILL.md")

    def test_custom_shared_path_is_not_printed(self) -> None:
        sentinel = "s3nt1nel-private-path-814"
        shared = self.sandbox / sentinel / "skills"

        result = self.run_commission(
            "probe", env=self.environment(SHARED_SKILLS=str(shared))
        )

        records = tuple(shared.glob("machine-*/SKILL.md"))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(len(records), 1)
        self.assertNotIn(sentinel, result.stdout + result.stderr + records[0].read_text())
        self.assertIn("record wrote custom", result.stdout)

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

    def test_record_projects_versions_and_paths_without_raw_values(self) -> None:
        sentinel = "s3nt1nel-private-material-581"
        wrapped_bin = self.sandbox / f"tools-{sentinel}"
        wrapped_bin.mkdir()
        for name in ("node", "npx", "npm", "bun", "claude", "codex", "opencode"):
            version = "release" if name == "bun" else "9.8.7"
            self.write_executable(
                wrapped_bin / name,
                textwrap.dedent(
                    f"""\
                    if [[ "${{1:-}}" == "--version" ]]; then
                      printf '%s\\n' '{name} {version} {{"session_token": "{sentinel}"}}'
                      exit 0
                    fi
                    exec "{self.fakebin / name}" "$@"
                    """
                ),
            )
        record = self.sandbox / "record.md"
        environment = self.environment(
            PATH=str(wrapped_bin) + os.pathsep + self.environment()["PATH"],
            SHELL=str(self.home / sentinel / "shell"),
            XDG_STATE_HOME=str(self.home / sentinel / "state"),
        )

        result = self.run_commission(
            "probe", "--record", str(record), env=environment
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        content = record.read_text()
        self.assertNotIn(sentinel, content)
        self.assertIn("Version: `9.8.7`", content)
        self.assertIn("- Shell: `custom`", content)
        self.assertIn("- XDG state home: `custom`", content)
        self.assertIn("- Shared skills: `$HOME/.agents/skills`", content)
        self.assertIn("- Bun: `custom`. Version: `present`", content)
        self.assertIn("| claude | yes | 9.8.7 | yes | pass |", content)

    def test_safe_output_redacts_structured_secret_values(self) -> None:
        sentinel = "s3nt1nel-private-material-662"
        flat = commission_module._safe_output(
            f'{{"session_token": "{sentinel}", "authorization": "Bearer {sentinel}"}}',
            "inventory",
        )
        nested = commission_module._safe_output(
            f'{{"session_token": {{"value": "{sentinel}"}}}}',
            "inventory",
        )

        self.assertNotIn(sentinel, flat)
        self.assertNotIn(sentinel, nested)
        self.assertEqual(
            flat,
            '{"session_token": <redacted>, "authorization": "Bearer <redacted>"}',
        )

    def test_probe_record_is_owner_only(self) -> None:
        record = self.sandbox / "record.md"

        result = self.run_commission("probe", "--record", str(record))

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)

    def test_probe_protects_existing_record_and_wizard(self) -> None:
        record = self.sandbox / "record.md"
        wizard = self.sandbox / "wizard.sh"
        record.write_text("keep record\n")
        wizard.write_text("keep wizard\n")

        result = self.run_commission(
            "probe", "--record", str(record), "--wizard", str(wizard)
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(record.read_text(), "keep record\n")
        self.assertEqual(wizard.read_text(), "keep wizard\n")
        self.assertEqual(len(tuple(self.sandbox.glob("record.md.impstack-backup.*"))), 1)
        self.assertEqual(len(tuple(self.sandbox.glob("wizard.sh.impstack-backup.*"))), 1)
        record_backup = next(self.sandbox.glob("record.md.impstack-backup.*"))
        wizard_backup = next(self.sandbox.glob("wizard.sh.impstack-backup.*"))
        self.assertEqual(record_backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(wizard_backup.stat().st_mode & 0o777, 0o700)
        self.assertIn("--force", result.stderr)

    def test_probe_protects_empty_existing_artifacts(self) -> None:
        record = self.sandbox / "record.md"
        wizard = self.sandbox / "wizard.sh"
        record.write_bytes(b"")
        wizard.write_bytes(b"")

        result = self.run_commission(
            "probe", "--record", str(record), "--wizard", str(wizard)
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(record.read_bytes(), b"")
        self.assertEqual(wizard.read_bytes(), b"")
        self.assertEqual(len(tuple(self.sandbox.glob("record.md.impstack-backup.*"))), 1)
        self.assertEqual(len(tuple(self.sandbox.glob("wizard.sh.impstack-backup.*"))), 1)
        self.assertIn("--force", result.stderr)

    def test_probe_force_replaces_backed_up_artifacts(self) -> None:
        record = self.sandbox / "record.md"
        wizard = self.sandbox / "wizard.sh"
        record.write_text("keep record\n")
        wizard.write_text("keep wizard\n")

        result = self.run_commission(
            "probe",
            "--record",
            str(record),
            "--wizard",
            str(wizard),
            "--force",
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertNotEqual(record.read_text(), "keep record\n")
        self.assertNotEqual(wizard.read_text(), "keep wizard\n")
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        self.assertEqual(wizard.stat().st_mode & 0o777, 0o700)
        self.assertEqual(len(tuple(self.sandbox.glob("record.md.impstack-backup.*"))), 1)
        self.assertEqual(len(tuple(self.sandbox.glob("wizard.sh.impstack-backup.*"))), 1)

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

    def test_proof_lane_installs_command_links(self) -> None:
        contract = json.loads(CONTRACT.read_text())
        proofs = [
            item for item in contract["assertions"] if item["id"].startswith("proof.")
        ]

        self.assertEqual(len(proofs), 1)
        self.assertEqual(proofs[0]["id"], "proof.install-bin")
        self.assertEqual(proofs[0]["command"], ["./install.sh", "bin"])


if __name__ == "__main__":
    unittest.main()
