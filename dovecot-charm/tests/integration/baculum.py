# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A simple Baculum API client for driving Bacula jobs in integration tests."""

import typing

import requests


class BaculumApiError(Exception):
    """Baculum API error."""

    def __init__(self, message: str, output: str, errno: int) -> None:
        """Initialize BaculumApiError.

        Args:
            message: error message.
            output: Baculum API output.
            errno: Baculum API error number.
        """
        super().__init__(f"{message}: {output} (error: {errno})")
        self.output = output
        self.errno = errno


class Baculum:
    """Baculum API client."""

    def __init__(self, base_url: str, username: str, password: str, timeout: int = 60):
        """Initialize Baculum API client.

        Args:
            base_url: Baculum API base URL.
            username: Baculum API username.
            password: Baculum API password.
            timeout: Baculum API request timeout.
        """
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.auth = (username, password)
        self._session.headers.update({"Content-Type": "application/json"})

    def _extract_output(self, operation: str, response: requests.Response) -> typing.Any:
        """Extract output from a Baculum API response.

        Args:
            operation: Baculum API operation name.
            response: Baculum API response object.

        Returns:
            The ``output`` field of the Baculum API response.

        Raises:
            BaculumApiError: if the Baculum API reports an error.
        """
        response.raise_for_status()
        result = response.json()
        output, error = result["output"], result["error"]
        if error:
            raise BaculumApiError(f"failed to {operation}", output, error)
        return output

    def run_backup_job(self, name: str) -> str:
        """Run a full backup job.

        Args:
            name: backup job name.

        Returns:
            Backup job output.
        """
        job = self.get_job(job=name)
        payload = {
            "name": name,
            "level": "F",  # Full backup
            "client": job["client"],
            "storage": job["storage"],
            "pool": job["pool"],
            "fileset": job["fileset"],
        }
        response = self._session.post(
            f"{self._base}/jobs/run", json=payload, timeout=self._timeout
        )
        return "\n".join(self._extract_output(f"run backup '{name}'", response))

    def run_restore_job(self, name: str, backup_job_id: int, source: str | None = None) -> str:
        """Run a restore job.

        Args:
            name: restore job name.
            backup_job_id: backup job run ID to restore.
            source: name of the backup job the data was originally backed up with.
                Defaults to ``name``, i.e. restoring onto the same client that produced
                the backup. Pass a different backup job name to restore data onto a
                different client, e.g. when restoring a backup taken on one charm unit
                onto a separately deployed unit.

        Returns:
            Baculum API output.
        """
        restore_job = self.get_job(job=name)
        backup_job = self.get_job(job=source) if source else restore_job
        payload = {
            "id": backup_job_id,
            "restorejob": name,
            "client": backup_job["client"],
            "restoreclient": restore_job["client"],
            "fileset": backup_job["fileset"],
            "where": "/",
            "replace": "always",
            "full": True,
        }
        response = self._session.post(
            f"{self._base}/jobs/restore", json=payload, timeout=self._timeout
        )
        return "\n".join(
            self._extract_output(f"restore '{name}' from backup {backup_job_id}", response)
        )

    def list_job_runs(self, name: str) -> list[dict]:
        """List job runs.

        Args:
            name: job name.

        Returns:
            A list of job run objects.
        """
        # Job names embed the owning bacula-fd subordinate's own unit name and are
        # therefore already unique, so filter by name alone. Filtering by client too
        # is unreliable for restores: a restore run's recorded client can be the
        # source (backup) client, the restore target client, or both depending on
        # the Bacula version, so an extra client filter can silently hide the run.
        params = {"name": name}
        response = self._session.get(f"{self._base}/jobs", params=params, timeout=self._timeout)
        return self._extract_output(f"list jobs '{name}'", response)

    def list_job_names(self) -> list[str]:
        """List job names.

        Returns:
            A list of job names.
        """
        response = self._session.get(f"{self._base}/jobs/resnames", timeout=self._timeout)
        result = self._extract_output("list job names", response)
        return next(iter(result.values()))

    def get_job(self, job: str) -> dict:
        """Get job details.

        Args:
            job: job name.

        Returns:
            Job details object.
        """
        params = {"name": job, "output": "json"}
        response = self._session.get(
            f"{self._base}/jobs/show", params=params, timeout=self._timeout
        )
        return self._extract_output(f"show job '{job}' detail", response)

    def list_job_files(self, job_id: int) -> list[str]:
        """List the files catalogued for a completed job run.

        Args:
            job_id: the job run ID whose backed up files to list.

        Returns:
            A list of full file paths backed up by the job.
        """
        response = self._session.get(f"{self._base}/jobs/{job_id}/files", timeout=self._timeout)
        return self._extract_output(f"list files for job {job_id}", response)
