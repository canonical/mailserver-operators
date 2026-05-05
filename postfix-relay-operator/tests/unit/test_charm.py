# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the Postfix relay charm."""

from pathlib import Path
from unittest.mock import ANY, Mock, call, patch

import ops.testing
import pytest
from charms.operator_libs_linux.v1 import systemd
from ops.testing import Context, State
from scenario import TCPPort

import charm
import state
import tls

FILES_PATH = Path(__file__).parent / "files"

DEFAULT_TLS_CONFIG_PATHS = tls.TLSConfigPaths(
    "/etc/ssl/private/dhparams.pem",
    "/etc/ssl/certs/ssl-cert-snakeoil.pem",
    "/etc/ssl/private/ssl-cert-snakeoil.key",
    "",
)


def test_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    arrange: Set up a charm state.
    act: Run the install event hook on the charm.
    assert: The unit status is set to maintenance and the correct packages are installed.
    """
    add_package_mock = Mock()
    monkeypatch.setattr(charm.apt, "add_package", add_package_mock)
    copytree_mock = Mock()
    monkeypatch.setattr(charm.shutil, "copytree", copytree_mock)
    write_file_mock = Mock()
    monkeypatch.setattr(charm.utils, "write_file", write_file_mock)
    service_start_mock = Mock()
    monkeypatch.setattr(charm.systemd, "service_start", service_start_mock)
    subprocess_mock = Mock()
    monkeypatch.setattr(charm, "subprocess", subprocess_mock)
    telegraf_snap_mock = Mock()
    snap_add_mock = Mock(return_value=telegraf_snap_mock)
    monkeypatch.setattr(charm.snap, "add", snap_add_mock)

    charm_state = State(config={}, leader=True)

    context = Context(charm.PostfixRelayCharm)
    out = context.run(context.on.install(), charm_state)

    assert out.unit_status == ops.testing.WaitingStatus()
    add_package_mock.assert_called_once_with(
        ["acl", "dovecot-core", "inotify-tools", "postfix", "postfix-policyd-spf-python"],
        update_cache=True,
    )
    copytree_mock.assert_called_once_with("files", "/", dirs_exist_ok=True)
    service_start_mock.assert_called_once_with(charm.INOTIFY_SERVICE_NAME)
    # Telegraf configuration
    snap_add_mock.assert_called_once_with(["telegraf"])
    subprocess_mock.check_call.assert_any_call(
        ["setfacl", "-Rm", "g:snap_daemon:rX", "/var/spool/postfix"], timeout=5
    )
    subprocess_mock.check_call.assert_any_call(
        ["setfacl", "-dm", "g:snap_daemon:rX", "/var/spool/postfix"], timeout=5
    )
    telegraf_snap_mock.restart.assert_called_once()


@patch(
    "charm.State.from_charm", Mock(side_effect=state.ConfigurationError("Invalid configuration"))
)
def test_invalid_config() -> None:
    """
    arrange: Invalid charm config.
    act: Run the config-changed event hook on the charm.
    assert: The unit status is set to blocked with the correct error message.
    """
    charm_state = State(config={}, leader=True)

    context = Context(charm.PostfixRelayCharm)
    out = context.run(context.on.config_changed(), charm_state)

    assert out.unit_status == ops.testing.BlockedStatus("Invalid config")


@patch("charm.subprocess.check_call", Mock())
class TestConfigureAuth:
    """Unit tests for _configure_auth."""

    @pytest.mark.parametrize(
        "smtp_auth_users",
        [pytest.param("", id="no auth users"), pytest.param("- user", id="with auth users")],
    )
    @patch("charm.systemd")
    @patch("charm.utils.write_file")
    def test_no_auth(
        self,
        write_file_mock: Mock,
        mock_systemd: "systemd",
        smtp_auth_users: str,
    ) -> None:
        """
        arrange: Charm with SMTP auth disabled.
        act: Run the config-changed event hook on the charm.
        assert: The charm correctly configures dovecot for a disabled state,
            pauses the dovecot service, and does not open SMTP auth ports.
        """
        charm_state = State(
            config={
                "enable_smtp_auth": False,
                "smtp_auth_users": smtp_auth_users,
            },
            leader=True,
        )

        context = Context(charm.PostfixRelayCharm)
        out = context.run(context.on.config_changed(), charm_state)

        assert {TCPPort(465), TCPPort(587)}.isdisjoint(out.opened_ports)

        expected_systemd_call = call("dovecot")
        assert expected_systemd_call in mock_systemd.service_pause.mock_calls
        assert expected_systemd_call not in mock_systemd.service_enable.mock_calls
        assert expected_systemd_call not in mock_systemd.service_reload.mock_calls

        expected_write_calls = [call(ANY, charm.DOVECOT_CONFIG_FILEPATH)]
        if smtp_auth_users:
            expected_write_calls.append(
                call(ANY, charm.DOVECOT_USERS_FILEPATH, perms=0o640, group=charm.DOVECOT_NAME)
            )

        write_file_mock.assert_has_calls(expected_write_calls)

        assert out.unit_status == ops.testing.ActiveStatus()

    @pytest.mark.parametrize(
        "dovecot_running",
        [pytest.param(True, id="dovecot_running"), pytest.param(False, id="dovecot_not_running")],
    )
    @patch("charm.systemd")
    @patch("charm.utils.write_file")
    def test_with_auth_dovecot(
        self,
        write_file_mock: Mock,
        mock_systemd: "systemd",
        dovecot_running: bool,
    ) -> None:
        """
        arrange: Charm with SMTP auth enabled and dovecot not running.
        act: Run the config-changed event hook on the charm.
        assert: Opensthe required ports, generates the dovecot config,
            and resumes the dovecot service.
        """
        charm_state = State(config={"enable_smtp_auth": True}, leader=True)
        mock_systemd.service_running.return_value = dovecot_running

        context = Context(charm.PostfixRelayCharm)
        out = context.run(context.on.config_changed(), charm_state)

        assert {TCPPort(465), TCPPort(587)}.issubset(out.opened_ports)

        expected_systemd_call = call("dovecot")
        if dovecot_running:
            assert expected_systemd_call in mock_systemd.service_reload.mock_calls
            assert expected_systemd_call not in mock_systemd.service_resume.mock_calls
            assert expected_systemd_call not in mock_systemd.service_pause.mock_calls
        else:
            assert expected_systemd_call in mock_systemd.service_resume.mock_calls
            assert expected_systemd_call not in mock_systemd.service_reload.mock_calls
            assert expected_systemd_call not in mock_systemd.service_pause.mock_calls

        write_file_mock.assert_has_calls([call(ANY, charm.DOVECOT_CONFIG_FILEPATH)])

        assert out.unit_status == ops.testing.ActiveStatus()


@pytest.mark.parametrize(
    "postfix_running",
    [pytest.param(True, id="postfix_running"), pytest.param(False, id="postfix_not_running")],
)
@patch.object(
    charm.postfix,
    "construct_postfix_config_params",
    wraps=charm.postfix.construct_postfix_config_params,
)
@patch.object(charm, "get_tls_config_paths", Mock(return_value=DEFAULT_TLS_CONFIG_PATHS))
@patch("charm.systemd")
@patch("charm.utils.write_file", Mock())
@patch("charm.subprocess.check_call")
def test_configure_relay(
    mock_subprocess_check_call: Mock,
    mock_systemd: "systemd",
    mock_construct_postfix_config_params: Mock,
    postfix_running: bool,
) -> None:
    """
    arrange: Configure the charm with a specific domain.
    act: Run the config-changed event hook.
    assert: The charm constructs the correct FQDN.
    """
    charm_state = State(
        config={
            "domain": "example-domain.com",
        },
        relations=[
            ops.testing.Relation(
                "milter",
                remote_units_data={
                    0: {"ingress-address": "10.0.0.10"},
                    1: {"ingress-address": "10.0.0.11", "port": "9999"},
                    2: {},
                },
            ),
            ops.testing.Relation(
                "milter",
                remote_units_data={
                    0: {"ingress-address": "10.0.1.10"},
                    1: {"ingress-address": "10.0.1.11", "port": "9999"},
                },
            ),
            ops.testing.Relation(
                "milter",
                remote_units_data={},
            ),
            ops.testing.Relation(
                "milter",
                remote_units_data={
                    0: {},
                    1: {"ingress-address": "10.0.1.10"},
                },
            ),
            ops.testing.PeerRelation(
                "peer",
                peers_data={
                    1: {},
                    2: {},
                },
            ),
        ],
        leader=True,
    )
    mock_systemd.service_running.return_value = postfix_running

    context = Context(charm.PostfixRelayCharm)
    out = context.run(context.on.config_changed(), charm_state)

    mock_construct_postfix_config_params.assert_called_once_with(
        charm_state=ANY,
        tls_dh_params_path=DEFAULT_TLS_CONFIG_PATHS.tls_dh_params,
        tls_cert_path=DEFAULT_TLS_CONFIG_PATHS.tls_cert,
        tls_key_path=DEFAULT_TLS_CONFIG_PATHS.tls_key,
        tls_cert_key_path=DEFAULT_TLS_CONFIG_PATHS.tls_cert_key,
        fqdn="postfix-relay-0.example-domain.com",
        hostname=ANY,
        milters="inet:10.0.0.11:9999 inet:10.0.1.10:8892",
    )

    mock_subprocess_check_call.assert_called_once_with(["newaliases"])
    expected_systemd_call = call("postfix")
    if postfix_running:
        assert expected_systemd_call in mock_systemd.service_reload.mock_calls
        assert expected_systemd_call not in mock_systemd.service_resume.mock_calls
    else:
        assert expected_systemd_call in mock_systemd.service_resume.mock_calls
        assert expected_systemd_call not in mock_systemd.service_reload.mock_calls

    assert out.unit_status == ops.testing.ActiveStatus()
    assert TCPPort(25) in out.opened_ports


class TestUpdateAliases:
    @patch("charm.utils.write_file")
    @patch("charm.subprocess.check_call")
    def testupdate_aliases_calls_newaliases(
        self,
        mock_check_call: Mock,
        _: Mock,
    ) -> None:
        """
        arrange: do nothing.
        act: Call the internal update_aliases method.
        assert: The 'newaliases' command is executed only if the file content changed.
        """
        charm.PostfixRelayCharm.update_aliases("admin@email.com")

        mock_check_call.assert_called_once_with(["newaliases"])

    @pytest.mark.parametrize(
        "initial_content, expected_content",
        [
            pytest.param(
                "",
                "devnull:       /dev/null\nroot:          admin@email.com\n",
                id="empty_file",
            ),
            pytest.param(
                "devnull:       /dev/null\n",
                "devnull:       /dev/null\nroot:          admin@email.com\n",
                id="missing_root",
            ),
            pytest.param(
                "root:          old@example.com\n",
                "devnull:       /dev/null\nroot:          admin@email.com\n",
                id="update_root",
            ),
            pytest.param(
                "postmaster:    root\n",
                "postmaster:    root\ndevnull:       /dev/null\nroot:          admin@email.com\n",
                id="preserve_existing_aliases",
            ),
            pytest.param(
                "devnull:       /dev/null\nroot:          admin@email.com\n",
                "devnull:       /dev/null\nroot:          admin@email.com\n",
                id="no_change",
            ),
        ],
    )
    @pytest.mark.parametrize(
        "admin_email_address",
        [
            pytest.param("admin@email.com", id="admin-email"),
            pytest.param(None, id="no-admin-email"),
        ],
    )
    @patch("charm.subprocess.check_call", Mock())
    def testupdate_aliases_content(
        self,
        admin_email_address: str | None,
        initial_content: str,
        expected_content: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        arrange: Parametrize different initial contents.
        act: Call the internal update_aliases method.
        assert: The content of the aliases file is updated to the expected state.
        """
        aliases_path = tmp_path / "aliases"
        aliases_path.write_text(initial_content)

        monkeypatch.setattr(charm, "ALIASES_FILEPATH", aliases_path)

        charm.PostfixRelayCharm.update_aliases(admin_email_address)

        if not admin_email_address:
            expected_content = "\n".join(
                [alias for alias in expected_content.split("\n") if not alias.startswith("root")]
            )

        assert aliases_path.read_text() == expected_content

    @patch("charm.subprocess.check_call", Mock())
    def testupdate_aliases_no_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        arrange: Define a path for an aliases file that does not exist.
        act: Call the internal update_aliases method.
        assert: The method creates the aliases file with the correct default content.
        """
        non_existing_path = tmp_path / "aliases"
        monkeypatch.setattr(charm, "ALIASES_FILEPATH", non_existing_path)

        charm.PostfixRelayCharm.update_aliases(None)

        assert non_existing_path.is_file()
        assert non_existing_path.read_text() == "devnull:       /dev/null\n"


@pytest.mark.parametrize(
    "enable_spf",
    [pytest.param(True, id="enable_spf"), pytest.param(False, id="disable_spf")],
)
@patch("charm.systemd", Mock())
@patch("charm.subprocess.check_call", Mock())
@patch("charm.utils.write_file")
def test_configure_policyd_spf(
    write_file_mock: Mock,
    enable_spf: bool,
) -> None:
    """
    arrange: Configure the charm state with SPF enabled or disabled.
    act: Run the config-changed event hook.
    assert: Configured only when SPF is enabled.
    """
    charm_state = State(
        config={
            "enable_spf": enable_spf,
            "spf_skip_addresses": "- 10.0.114.0/24",
        }
    )

    context = Context(charm.PostfixRelayCharm)
    out = context.run(context.on.config_changed(), charm_state)

    investigated_call = call(ANY, charm.POLICYD_SPF_FILEPATH)

    if enable_spf:
        write_file_mock.assert_has_calls([investigated_call])
    else:
        assert investigated_call not in write_file_mock.mock_calls

    assert out.unit_status == ops.testing.ActiveStatus()
