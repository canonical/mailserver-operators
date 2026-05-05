# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests."""

import getpass
import json
import os
import subprocess  # nosec B404
import tempfile
import typing
from pathlib import Path
from secrets import token_hex
from unittest.mock import ANY, MagicMock, call

import ops.testing
import pytest

import charm
import utils
from charm import OpenDKIMCharm


def test_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    arrange: Mock snap installs and prepare a trivial context and state.
    act: Run install hook.
    assert: OpenDKIM and Telegraf snaps were installed and the unit is waiting.
    """
    # Mock subprocess.run to simulate snap not present
    subprocess_run_mock = MagicMock()
    subprocess_run_mock.returncode = 1
    monkeypatch.setattr(subprocess, "run", subprocess_run_mock)

    # Mock SnapCache for opendkim snap
    opendkim_snap_mock = MagicMock()
    opendkim_snap_mock.present = False
    snap_cache_mock = MagicMock()
    snap_cache_mock.__getitem__.return_value = opendkim_snap_mock
    monkeypatch.setattr("charm.snap.SnapCache", MagicMock(return_value=snap_cache_mock))

    telegraf_snap_mock = MagicMock()
    snap_add_mock = MagicMock(return_value=telegraf_snap_mock)
    monkeypatch.setattr(charm.snap, "add", snap_add_mock)
    telegraf_conf = tmp_path / "telegraf.conf"
    monkeypatch.setattr(charm, "TELEGRAF_CONF_DST", telegraf_conf)

    write_file_mock = MagicMock()
    monkeypatch.setattr("utils.write_file", write_file_mock)
    update_logrotate_conf_mock = MagicMock()
    monkeypatch.setattr("utils.update_logrotate_conf", update_logrotate_conf_mock)

    context = ops.testing.Context(
        charm_type=OpenDKIMCharm,
    )
    base_state: dict[str, str] = {}
    state = ops.testing.State(**base_state)
    out = context.run(context.on.install(), state)
    write_file_mock.assert_called_with(Path("/etc/logrotate.d/rsyslog"), ANY, 0o644, user="root")
    assert len(out.opened_ports) == 1
    assert next(iter(out.opened_ports)).port == 8892
    assert out.unit_status.name == ops.testing.WaitingStatus.name

    # Telegraf configuration
    snap_add_mock.assert_called_once_with(["telegraf"])
    write_file_mock.assert_has_calls([call(telegraf_conf, ANY, 0o644, user="root")])
    telegraf_snap_mock.restart.assert_called_once()

    # OpenDKIM snap installation from store
    opendkim_snap_mock.ensure.assert_called_once()


@pytest.mark.parametrize(
    "signingtable,keytable,private_keys,error_messages",
    [
        pytest.param(
            None,
            None,
            None,
            ["empty signingtable", "empty keytable", "empty private-keys"],
            id="No config options",
        ),
        pytest.param(
            "",
            "",
            None,
            ["empty signingtable", "empty keytable", "empty private-keys"],
            id="Empty config options",
        ),
        pytest.param(
            "*wrongyaml",
            "*wrongyaml",
            {},
            ["wrong signingtable", "wrong keytable"],
            id="Wrong YAML formats",
        ),
        pytest.param(
            "signingtable",
            "keytable",
            {},
            ["wrong", " signingtable,keytable."],
            id="Wrong YAML config options",
        ),
        pytest.param(
            json.dumps([["valid", "valid"]]),
            "keytable",
            {},
            ["wrong", " keytable."],
            id="Wrong YAML config options",
        ),
        pytest.param(
            "signingtable",
            json.dumps([["*@example.com", "selector._domainkey.example.com"]]),
            {},
            ["wrong", " signingtable."],
            id="Wrong YAML config options",
        ),
    ],
)
def test_invalid_config(signingtable, keytable, private_keys, error_messages):
    """
    arrange: Prepare a configuration options and key secrets that is invalid.
    act: Send hook on config_changed.
    assert: Test that the charm is blocked and the correct message is shown..
    """
    context = ops.testing.Context(
        charm_type=OpenDKIMCharm,
    )

    config: dict[str, str] = {}
    secrets: ops.testing.Secret = {}
    if signingtable is not None:
        config["signingtable"] = signingtable
    if keytable is not None:
        config["keytable"] = keytable
    if private_keys is not None:
        secret_id = token_hex(20)[:20]
        config["private-keys"] = f"secret:{secret_id}"
        secrets = {ops.testing.Secret(id=f"secret:{secret_id}", tracked_content=private_keys)}
    base_state: dict[str, typing.Any] = {"config": config, "secrets": secrets}
    state = ops.testing.State(**base_state)
    out = context.run(context.on.config_changed(), state)
    assert out.unit_status.name == ops.testing.BlockedStatus.name
    for error_message in error_messages:
        assert error_message in out.unit_status.message


def test_missing_milter_relation():
    """
    arrange: Prepare a valid configuration and apply it.
    act: Send hook on config_changed.
    assert: The charmed is blocked because there is no valid milter relation.
    """
    context = ops.testing.Context(
        charm_type=OpenDKIMCharm,
    )

    secret_id = token_hex(20)[:20]
    secrets = {
        ops.testing.Secret(id=f"secret:{secret_id}", tracked_content={"thekey": "PRIVATEKEY"})
    }
    config = {
        "signingtable": json.dumps([["*@example.com", "selector._domainkey.example.com"]]),
        "keytable": json.dumps(
            [
                [
                    "selector._domainkey.example.com",
                    "example.com:selector:/etc/dkimkeys/thekey.private",
                ]
            ]
        ),
        "private-keys": f"secret:{secret_id}",
    }
    base_state: dict[str, typing.Any] = {"config": config, "secrets": secrets}
    state = ops.testing.State(**base_state)
    out = context.run(context.on.config_changed(), state)
    assert out.unit_status.name == ops.testing.BlockedStatus.name
    assert "milter" in out.unit_status.message


@pytest.mark.parametrize(
    "initial_opendkim_conf,restart_expected",
    [
        pytest.param("", True, id="Initial opendkim.conf empty, restart service"),
        pytest.param(
            (Path(__file__).parent / "files/base_opendkim.conf").read_text(),
            False,
            id="opendkim.conf not changed, do not restart service",
        ),
    ],
)
def test_correct_config(
    initial_opendkim_conf, restart_expected, base_state, tmp_path: Path, monkeypatch
):
    """
    arrange: Mock all external accesses and prepare a valid configuration with a milter relation.
    act: Run install hook, then config_changed hook.
    assert: The charm is active. Files are written and the service is restarted/reloaded via snap.
    """
    if restart_expected:
        read_text_mock = MagicMock(return_value="")
    else:
        signingtable_content = (Path(__file__).parent / "files/base_signingtable").read_text()
        keytable_content = (Path(__file__).parent / "files/base_keytable").read_text()

        def read_text_side_effect(path):
            name = Path(path).name
            match name:
                case "key1.private":
                    return "PRIVATEKEY1"
                case "key2.private":
                    return "PRIVATEKEY2"
                case "signingtable":
                    return signingtable_content
                case "keytable":
                    return keytable_content
                case "opendkim.conf":
                    return initial_opendkim_conf
                case _:
                    return ""

        read_text_mock = MagicMock(side_effect=read_text_side_effect)

    monkeypatch.setattr("utils.read_text", read_text_mock)
    monkeypatch.setattr("charm.validate_opendkim", MagicMock(return_value=None))
    subprocess_run_mock = MagicMock(return_value=MagicMock(stdout="LISTEN"))
    monkeypatch.setattr("charm.subprocess.run", subprocess_run_mock)
    write_calls = []

    def write_file_mock(path, content, mode, user=None):
        write_calls.append((path, content, mode, user))

    monkeypatch.setattr("utils.write_file", write_file_mock)

    opendkim_snap_mock = MagicMock()
    telegraf_snap_mock = MagicMock()
    monkeypatch.setattr(charm.snap, "add", MagicMock(return_value=telegraf_snap_mock))
    telegraf_conf = tmp_path / "telegraf.conf"
    monkeypatch.setattr(charm, "TELEGRAF_CONF_DST", telegraf_conf)

    monkeypatch.setattr("charm.Path.exists", MagicMock(return_value=True))

    snap_cache_mock = MagicMock()
    snap_cache_mock.__getitem__ = MagicMock(return_value=opendkim_snap_mock)
    monkeypatch.setattr("charm.snap.SnapCache", MagicMock(return_value=snap_cache_mock))

    context = ops.testing.Context(
        charm_type=OpenDKIMCharm,
    )

    state = ops.testing.State(**base_state)
    out = context.run(context.on.config_changed(), state)

    assert out.unit_status.name == ops.testing.ActiveStatus.name
    assert next(iter(out.relations)).local_unit_data["port"] == "8892"

    if restart_expected:
        assert len(write_calls) == 5
        opendkim_snap_mock.restart.assert_called_once()
        write_paths = {c[0] for c in write_calls}
        assert Path("/var/snap/opendkim/current/etc/opendkim.conf") in write_paths
        assert Path("/var/snap/opendkim/current/etc/dkimkeys/key1.private") in write_paths
        assert Path("/var/snap/opendkim/current/etc/dkimkeys/key2.private") in write_paths
        assert Path("/var/snap/opendkim/current/etc/dkimkeys/signingtable") in write_paths
        assert Path("/var/snap/opendkim/current/etc/dkimkeys/keytable") in write_paths
    else:
        assert len(write_calls) == 0, f"Unexpected write calls: {[str(c[0]) for c in write_calls]}"
        opendkim_snap_mock.restart.assert_not_called()


def test_write_file():
    """
    arrange: Prepare some text and a directory.
    act: Call write_file.
    assert: The file is rendered with the correct content.
    """
    user = getpass.getuser()
    with tempfile.TemporaryDirectory() as tmpdir:
        content = "any text"
        path = Path(tmpdir) / "onefile.txt"
        utils.write_file(path, content, 0o666, user=user)
        st = os.stat(str(path))
        assert oct(st.st_mode) == "0o100666"
        assert path.read_text() == content
