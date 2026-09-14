"""Special agent tests with a fake Net-SNMP. Output formats mirror the real NX-OS captures."""

import stat
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType

import pytest

FAKE_AUTH = "fake-auth-passphrase"
FAKE_PRIV = "fake-priv-passphrase"

WALK = "\n".join(
    [
        ".1.3.6.1.4.1.9.9.468.1.5.1.2.1.49.1 = Hex-STRING: 01 00 00 00 ",
        ".1.3.6.1.4.1.9.9.468.1.5.1.2.2.51.48.1 = Hex-STRING: 1E 00 00 00 ",
        ".1.3.6.1.4.1.9.9.468.1.5.1.2.3.50.48.48.1 = Hex-STRING: C8 00 00 00 ",
        ".1.3.6.1.4.1.9.9.468.1.5.1.2.4.49.50.49.50.1 = Hex-STRING: BC 04 00 00 ",
        ".1.3.6.1.4.1.9.9.468.1.5.1.2.6.118.108.97.110.45.49.1 = Hex-STRING: 01 00 00 00 ",
        ".1.3.6.1.4.1.9.9.468.1.5.1.2.8.118.108.97.110.45.50.48.48.1 = Hex-STRING: C8 00 00 00 ",
    ]
)

GETS = {
    (None, ".1.3.6.1.2.1.1.3.0"): ".1.3.6.1.2.1.1.3.0 = Timeticks: (2590160436) 299 days, 18:53:24.36",
    ("1", ".1.3.6.1.2.1.17.2.4.0"): ".1.3.6.1.2.1.17.2.4.0 = Counter32: 6",
    ("1", ".1.3.6.1.2.1.17.2.3.0"): ".1.3.6.1.2.1.17.2.3.0 = Timeticks: (2586192400) 299 days, 7:52:04.00",
    ("200", ".1.3.6.1.2.1.17.2.4.0"): ".1.3.6.1.2.1.17.2.4.0 = Counter32: 37",
    ("200", ".1.3.6.1.2.1.17.2.3.0"): ".1.3.6.1.2.1.17.2.3.0 = Timeticks: 2586624300",
    ("1212", ".1.3.6.1.2.1.17.2.4.0"): ".1.3.6.1.2.1.17.2.4.0 = No Such Instance currently exists at this OID",
}


class FakeSnmp:
    def __init__(self, walk_rc: int = 0) -> None:
        self.walk_rc = walk_rc
        self.commands: list[list[str]] = []
        self.conf_checks: list[tuple[int, str]] = []

    def __call__(
        self, command: Sequence[str], env: Mapping[str, str]
    ) -> subprocess.CompletedProcess[str]:
        command = list(command)
        self.commands.append(command)
        conf = Path(env["SNMPCONFPATH"], "snmp.conf")
        self.conf_checks.append((stat.S_IMODE(conf.stat().st_mode), conf.read_text()))
        context = command[command.index("-n") + 1] if "-n" in command else None
        oid = command[-1]
        if Path(command[0]).name == "snmpwalk":
            if self.walk_rc:
                return subprocess.CompletedProcess(command, 1, "", "Timeout: No Response from udp:192.0.2.10:161.\n")
            return subprocess.CompletedProcess(command, 0, WALK, "")
        if context == "30":
            return subprocess.CompletedProcess(command, 1, "", "Timeout: No Response from udp:192.0.2.10:161.\n")
        return subprocess.CompletedProcess(command, 0, GETS.get((context, oid), "") + "\n", "")


ARGV = [
    "--host", "192.0.2.10",
    "--user", "monitor",
    "--auth-protocol", "sha",
    "--auth-password-id", "auth_id:/omd/sites/x/var/check_mk/stored_passwords",
    "--priv-protocol", "aes",
    "--priv-password-id", "priv_id:/omd/sites/x/var/check_mk/stored_passwords",
]  # fmt: skip


@pytest.fixture
def fake_secrets(agent_module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = {"auth_id": FAKE_AUTH, "priv_id": FAKE_PRIV}
    monkeypatch.setattr(agent_module, "resolve_secret", lambda ref: secrets[ref.split(":")[0]])


def test_decode_context_table(agent_module: ModuleType) -> None:
    contexts = agent_module.parse_context_map(WALK)
    assert contexts == {"1": 1, "30": 30, "200": 200, "1212": 1212, "vlan-1": 1, "vlan-200": 200}
    assert agent_module.numeric_vlan_contexts(contexts) == [1, 30, 200, 1212]


def test_full_run(
    agent_module: ModuleType, fake_secrets: None, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeSnmp()
    assert agent_module.main(ARGV, runner=fake) == 0
    assert capsys.readouterr().out.splitlines() == [
        "<<<nxos_stp_tcn:sep(59)>>>",
        "sysuptime;2590160436",
        "vlan;1;ok;6;2586192400",
        "vlan;30;timeout;;",
        "vlan;200;ok;37;2586624300",
        "vlan;1212;nosuch;;",
    ]
    contexts = [c[c.index("-n") + 1] for c in fake.commands if "-n" in c]
    assert not any(ctx.startswith("vlan-") for ctx in contexts)  # vlan-<id> is unreliable
    # one OID per request (NX-OS answers only the first varbind inside a context)
    assert all(c[-1].startswith(".1.3.6.1") and not c[-2].startswith(".1.3.6.1") for c in fake.commands)


def test_credentials_never_on_command_line_and_conf_is_private(
    agent_module: ModuleType, fake_secrets: None, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeSnmp()
    agent_module.main(ARGV, runner=fake)
    for command in fake.commands:
        assert FAKE_AUTH not in " ".join(command) and FAKE_PRIV not in " ".join(command)
        assert "monitor" not in command  # user name also only in the config file
    mode, text = fake.conf_checks[0]
    assert mode == 0o600
    assert f'defAuthPassphrase "{FAKE_AUTH}"' in text
    assert f'defPrivPassphrase "{FAKE_PRIV}"' in text
    assert "defSecurityLevel authPriv" in text
    output = capsys.readouterr()
    assert FAKE_AUTH not in output.out + output.err


def test_temporary_config_is_removed(agent_module: ModuleType, fake_secrets: None) -> None:
    seen: list[str] = []

    def runner(command: Sequence[str], env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
        seen.append(env["SNMPCONFPATH"])
        return FakeSnmp()(command, env)

    agent_module.main(ARGV, runner=runner)
    assert seen and not Path(seen[0]).exists()


def test_walk_failure_is_reported_without_secrets(
    agent_module: ModuleType, fake_secrets: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert agent_module.main(ARGV, runner=FakeSnmp(walk_rc=1)) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "Cannot read the VLAN context table: Timeout" in output.err
    assert FAKE_AUTH not in output.err and FAKE_PRIV not in output.err


def test_auth_priv_requires_priv_arguments(
    agent_module: ModuleType, fake_secrets: None, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ARGV[: ARGV.index("--priv-protocol")]
    assert agent_module.main(argv, runner=FakeSnmp()) == 1
    assert "authPriv requires" in capsys.readouterr().err


def test_auth_no_priv_conf(agent_module: ModuleType) -> None:
    creds = agent_module.Credentials("monitor", "authNoPriv", "SHA", "x" * 8)
    text = agent_module.render_snmp_conf(creds, "/tmp/d")
    assert "defSecurityLevel authNoPriv" in text and "defPriv" not in text
    assert "x" * 8 not in repr(creds)


def test_conf_quoting(agent_module: ModuleType) -> None:
    creds = agent_module.Credentials("mon", "authNoPriv", "SHA", 'a"b\\c!d e')
    assert 'defAuthPassphrase "a\\"b\\\\c!d e"' in agent_module.render_snmp_conf(creds, "/t")
    with pytest.raises(ValueError):
        agent_module.render_snmp_conf(
            agent_module.Credentials("mon", "authNoPriv", "SHA", "a\nb"), "/t"
        )


@pytest.mark.parametrize(
    "stdout, stderr, rc, expected",
    [
        (".1.3.6.1.2.1.17.2.4.0 = Counter32: 37\n", "", 0, ("ok", "37")),
        (".1.3.6.1.2.1.17.2.3.0 = Timeticks: (10369600) 1 day, 4:48:16.00\n", "", 0, ("ok", "10369600")),
        (".1.3.6.1.2.1.17.2.3.0 = Timeticks: 10369600\n", "", 0, ("ok", "10369600")),
        (".1.3.6.1.2.1.17.2.3.0 = No Such Object available on this agent at this OID\n", "", 0, ("nosuch", None)),
        ("", "Timeout: No Response from udp:192.0.2.10:161.\n", 1, ("timeout", None)),
        ("", "snmpget: Authentication failure (incorrect password, community or key)\n", 1, ("error", None)),
        (".1.3.6.1.2.1.17.2.4.0 = STRING: \"garbage\"\n", "", 0, ("error", None)),
    ],
)
def test_parse_get(
    agent_module: ModuleType, stdout: str, stderr: str, rc: int, expected: tuple[str, str | None]
) -> None:
    result = agent_module.parse_get(subprocess.CompletedProcess([], rc, stdout, stderr))
    assert (result.status, result.value) == expected


def test_password_lookup_failure_is_wrapped(agent_module: ModuleType) -> None:
    with pytest.raises(agent_module.PasswordLookupError, match="'some_id'"):
        agent_module.resolve_secret("some_id:/nonexistent/stored_passwords")
