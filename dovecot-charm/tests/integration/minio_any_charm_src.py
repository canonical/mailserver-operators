import os
import subprocess
import textwrap
import urllib.request

import ops
from any_charm_base import AnyCharmBase


class AnyCharm(AnyCharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.install, self._on_install)

    def _on_install(self, _):
        self.unit.status = ops.MaintenanceStatus("downloading minio")
        urllib.request.urlretrieve(
            "https://dl.min.io/server/minio/release/linux-amd64/minio", "/usr/bin/minio"
        )
        os.chmod("/usr/bin/minio", 0o755)
        self.unit.status = ops.MaintenanceStatus("setting up minio")
        service = textwrap.dedent(
            """
            [Unit]
            Description=minio
            Wants=network-online.target
            After=network-online.target

            [Service]
            Type=simple
            Environment="MINIO_ROOT_USER=minioadmin"
            Environment="MINIO_ROOT_PASSWORD=minioadmin"
            ExecStartPre=/usr/bin/mkdir -p /srv/bacula
            ExecStart=/usr/bin/minio server --console-address :9001 /srv
            Restart=on-failure
            RestartSec=5

            [Install]
            WantedBy=multi-user.target
            """
        )
        with open("/etc/systemd/system/minio.service", "w") as f:
            f.write(service)
        subprocess.check_call(["systemctl", "daemon-reload"])
        subprocess.check_call(["systemctl", "enable", "--now", "minio"])
        self.unit.set_ports(9000, 9001)
        self.unit.status = ops.ActiveStatus()
