"""README.md's examples, run as written against real servers.

Every code block in README.md preceded by a ``<!-- test: KIND [NAME] -->`` comment is used:

- ``file PATH``: written to PATH in the example project;
- ``server [NAME]``: started in the background (the quick start's server, or NAME's);
- ``shell [NAME]``: run with bash in the project directory (NAME's scenario);
- ``output``: lines the quick start's last command must print;
- ``profile NAME``: profiles.yml for NAME's scenario, which runs ``dbt debug`` and checks the
  signed-in user;
- ``install``: run by CI (the Installation commands), not here.

The servers listen on 31337, the README's port, one at a time: the tests of this file run in
order on one worker (``--dist loadfile``). Port 31337 is below Linux's ephemeral range, so the
other tests' servers never take it.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.conftest import clean_environment, make_certificates, server_binary

README = Path(__file__).resolve().parents[2] / "README.md"
SUPPORT = Path(__file__).resolve().parents[1] / "support"
BLOCK = re.compile(
    pattern=r"<!-- test: (?P<kind>\w+)(?: (?P<name>[^ ]+))? -->\n```[\w-]*\n(?P<body>.*?)```",
    flags=re.DOTALL,
)


def readme_blocks() -> list[tuple[str, str | None, str]]:
    return [
        (match["kind"], match["name"], match["body"])
        for match in BLOCK.finditer(string=README.read_text())
    ]


def blocks(kind: str, name: str | None = None) -> list[str]:
    return [body for k, n, body in readme_blocks() if k == kind and n == name]


def one_block(kind: str, name: str | None = None) -> str:
    found = blocks(kind=kind, name=name)
    assert len(found) == 1, f"README.md needs exactly one `test: {kind} {name or ''}` block"
    return found[0]


def environment(home: Path, **extra: str) -> dict[str, str]:
    """The examples' environment: no HARDCHARGER_* from the shell running the tests, and
    hardcharger-server and dbt on the PATH."""
    env = clean_environment(home=home)
    env["PATH"] = os.pathsep.join(
        [str(Path(server_binary()).parent), str(Path(sys.executable).parent), env["PATH"]]
    )
    env.update(extra)
    return env


def run_shell(script: str, cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        args=["bash", "-euo", "pipefail", "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        f"README example failed ({result.returncode}):\n{script}\n"
        f"--- stdout\n{result.stdout}\n--- stderr\n{result.stderr}"
    )
    return result.stdout


class ReadmeServer:
    """A server started by a README block (or, for browser sign-in, by the test) on 31337."""

    def __init__(self, args: list[str], cwd: Path, env: dict[str, str]):
        self.log = cwd / "server.log"
        with self.log.open(mode="ab") as out:
            self.process = subprocess.Popen(
                args=args, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT
            )
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            try:
                with urllib.request.urlopen(
                    url="https://127.0.0.1:31337/warp", timeout=2, context=context
                ):
                    return
            except (urllib.error.URLError, OSError) as error:
                if "CERTIFICATE_REQUIRED" in str(error):
                    return
            time.sleep(0.2)
        self.stop()
        pytest.fail(reason=f"the README's server did not start:\n{self.log.read_text()[-3000:]}")

    @classmethod
    def from_block(cls, block: str, cwd: Path, env: dict[str, str]) -> "ReadmeServer":
        # The block's last command runs the server; the ones before it prepare it.
        *setup, command = [line for line in block.replace("\\\n", " ").splitlines() if line]
        if setup:
            run_shell(script="\n".join(setup), cwd=cwd, env=env)
        # `exec env` so the server is this process (assignments before the command work too).
        return cls(args=["bash", "-c", f"exec env {command}"], cwd=cwd, env=env)

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


@pytest.fixture(scope="module")
def home(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("readme-home")


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    """The quick start's project, with every `file` block of the README."""
    root = tmp_path_factory.mktemp("readme") / "shop"
    root.mkdir()
    for path in [n for k, n, _ in readme_blocks() if k == "file"]:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data=one_block(kind="file", name=path))
    return root


@pytest.fixture(scope="module")
def quick_start_server(project, home):
    server = ReadmeServer.from_block(
        block=one_block(kind="server"), cwd=project, env=environment(home=home)
    )
    yield server
    server.stop()


def test_the_readme_has_its_examples():
    kinds = [(kind, name) for kind, name, _ in readme_blocks()]
    for expected in (
        ("install", None),
        ("server", None),
        ("shell", None),
        ("output", None),
        ("shell", "token"),
        ("profile", "token"),
        ("server", "mtls"),
        ("profile", "mtls"),
        ("profile", "external"),
    ):
        assert expected in kinds, expected
    assert len([k for k in kinds if k[0] == "file"]) >= 10


def test_quick_start(project, home, quick_start_server):
    # copied_orders.py reads from a "source" Hardcharger server: the quick start's own.
    env = environment(
        home=home,
        SOURCE_URI="hardcharger://localhost:31337",
        SOURCE_USERNAME="hardcharger",
        SOURCE_PASSWORD="change-me",
        SOURCE_TLS_ROOT_CERTS=str(project / "server.pem"),
    )
    out = run_shell(script=one_block(kind="shell"), cwd=project, env=env)
    for line in one_block(kind="output").splitlines():
        assert line in out, f"{line!r} is not in the output:\n{out}"

    # The other models of the README did what it says.
    queries = [
        "select count(*) as n, min(id) as lo, max(id) as hi from {{ ref('numbers') }}",
        "select count(*) as n from {{ ref('copied_orders') }}",
        "select string_agg(id::varchar, ',' order by id) as ids from {{ ref('large_orders') }}",
        "select count(*) as n from {{ ref('orders_export') }}",
        "select string_agg(distinct month, ',' order by month) as months "
        "from {{ ref('orders_by_month') }}",
    ]
    check = "\n".join(f'dbt show --inline "{query}"' for query in queries)
    out = run_shell(script=check, cwd=project, env={**env, "HARDCHARGER_PASSWORD": "change-me"})
    for expected in ("| 3000 |  0 | 2999 |", "| 4 |", "| 1,3 |", "| 2026-03,2026-04 |"):
        assert expected in out, f"{expected!r} is not in:\n{out}"
    assert (project / "orders_export.parquet").is_file()
    assert sorted(p.name for p in (project / "orders_by_month").iterdir()) == [
        "month=2026-03",
        "month=2026-04",
    ]


def signed_in_user(scenario: Path, env: dict[str, str]) -> str:
    out = run_shell(
        script='dbt debug\ndbt show --inline "select HARDCHARGER_USER() as signed_in_as"',
        cwd=scenario,
        env=env,
    )
    assert "All checks passed!" in out, out
    return out


def scenario_dir(project: Path, name: str) -> Path:
    """A copy of the quick start's project with NAME's profiles.yml."""
    scenario = project.parent / name
    shutil.copytree(src=project, dst=scenario, ignore=shutil.ignore_patterns("target", "logs"))
    (scenario / "profiles.yml").write_text(data=one_block(kind="profile", name=name))
    return scenario


def test_token_profile(project, home, quick_start_server):
    scenario = scenario_dir(project=project, name="token")
    script = one_block(kind="shell", name="token")
    env = environment(home=home)
    out = run_shell(
        script=script
        + '\ndbt debug\ndbt show --inline "select HARDCHARGER_USER() as signed_in_as"',
        cwd=scenario,
        env=env,
    )
    assert "All checks passed!" in out, out
    assert "| hardcharger  |" in out, out


def test_client_certificate_profile(project, home, quick_start_server):
    quick_start_server.stop()  # its port is the next server's
    scenario = scenario_dir(project=project, name="mtls")
    certs = make_certificates(out_dir=scenario, clients={"analyst": "analyst@example.com"})
    certs["key"].rename(target=scenario / "server.key")
    server = ReadmeServer.from_block(
        block=one_block(kind="server", name="mtls"), cwd=scenario, env=environment(home=home)
    )
    try:
        out = signed_in_user(scenario=scenario, env=environment(home=home))
        assert "| analyst@example.com |" in out, out
    finally:
        server.stop()


AUDIENCE = "dbt-hardcharger-readme"
CLIENT_ID = "dbt-hardcharger-readme-client"
CLIENT_SECRET = "dbt-hardcharger-readme-secret"


def test_browser_sign_in_profile(project, home, quick_start_server):
    quick_start_server.stop()
    scenario = scenario_dir(project=project, name="external")
    certs = make_certificates(out_dir=scenario)
    idp = subprocess.Popen(
        args=[sys.executable, str(SUPPORT / "mock_idp.py"), AUDIENCE, CLIENT_ID, CLIENT_SECRET],
        stdout=subprocess.PIPE,
        text=True,
    )
    server = None
    try:
        issuer = idp.stdout.readline().strip()
        assert issuer.startswith("http://127.0.0.1:"), issuer
        env = environment(home=home, HARDCHARGER_ADMIN_PASSWORD="change-me")
        server = ReadmeServer(
            args=[
                server_binary(),
                "--tls-cert",
                str(certs["cert"]),
                "--tls-key",
                str(certs["key"]),
                "--token-allowed-issuer",
                issuer,
                "--token-allowed-audience",
                AUDIENCE,
                "--token-default-role",
                "admin",
                "--token-authorized-emails",
                "*@example.com",
                "--oauth-client-id",
                CLIENT_ID,
                "--oauth-client-secret",
                CLIENT_SECRET,
            ],
            cwd=scenario,
            env=env,
        )
        sign_ins = scenario / "sign-ins.log"
        browser = f"{sys.executable} {SUPPORT / 'fake_browser.py'} {sign_ins} code-ok"
        out = signed_in_user(
            scenario=scenario, env=environment(home=home, HARDCHARGER_BROWSER=browser)
        )
        assert "| analyst@example.com |" in out, out
        # dbt debug and dbt show are two processes: one sign-in each, although each also
        # asks the server for its catalog and schema (the profile names neither).
        assert sign_ins.read_text().count("sign-in") == 2
    finally:
        if server is not None:
            server.stop()
        idp.kill()
        idp.wait()
