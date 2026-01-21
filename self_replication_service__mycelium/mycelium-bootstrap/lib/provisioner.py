"""SporeStack API client for VPS provisioning."""

import logging
import time
from typing import Dict, List, Optional, Any

import requests

logger = logging.getLogger(__name__)


class SporeStackError(Exception):
    """Base exception for SporeStack operations."""
    pass


class ServerNotReadyError(SporeStackError):
    """Raised when server is not yet ready after timeout."""
    pass


class InsufficientBalanceError(SporeStackError):
    """Raised when token balance is insufficient."""
    pass


class SporeStackClient:
    """SporeStack API client. Docs: https://api.sporestack.com/docs"""

    BASE_URL = "https://api.sporestack.com"
    DEFAULT_TIMEOUT = 30

    # Default server config ~ $46.20
    DEFAULT_PROVIDER = "vultr"
    DEFAULT_FLAVOR = "vhp-2c-4gb-amd"
    DEFAULT_REGION = "ams"  # Amsterdam
    DEFAULT_OS = "ubuntu-24.04"
    DEFAULT_DAYS = 30

    def __init__(self, token: str):
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Make an API request, returning response JSON."""
        url = f"{self.BASE_URL}{endpoint}"

        kwargs.setdefault("timeout", self.DEFAULT_TIMEOUT)

        try:
            response = self.session.request(method, url, **kwargs)

            # Log request details for debugging
            logger.debug(f"{method} {url} -> {response.status_code}")

            if response.status_code >= 400:
                error_msg = response.text
                try:
                    error_data = response.json()
                    error_msg = error_data.get("detail", error_msg)
                except Exception:
                    pass

                raise SporeStackError(
                    f"API error ({response.status_code}): {error_msg}"
                )

            if response.status_code == 204:  # No content
                return {}

            return response.json()

        except requests.RequestException as e:
            raise SporeStackError(f"Request failed: {e}")

    def get_balance(self) -> Dict[str, Any]:
        """Get token balance (cents, usd, burn_rate)."""
        return self._request("GET", f"/token/{self.token}/balance")

    def get_token_info(self) -> Dict[str, Any]:
        """Get detailed token information."""
        return self._request("GET", f"/token/{self.token}/info")

    def create_invoice(
        self,
        dollars: int,
        currency: str = "btc",
        affiliate: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a funding invoice. Minimum $5."""
        if dollars < 5:
            raise SporeStackError("Minimum invoice amount is $5")

        payload = {
            "dollars": dollars,
            "currency": currency.lower(),
        }

        if affiliate:
            payload["affiliate"] = affiliate

        return self._request(
            "POST",
            f"/token/{self.token}/add",
            json=payload
        )

    def list_invoices(self) -> List[Dict[str, Any]]:
        return self._request("GET", f"/token/{self.token}/invoices")

    def get_invoice(self, invoice_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/token/{self.token}/invoices/{invoice_id}")

    def launch_server(
        self,
        ssh_key: str,
        flavor: Optional[str] = None,
        operating_system: Optional[str] = None,
        provider: Optional[str] = None,
        days: Optional[int] = None,
        hostname: Optional[str] = None,
        autorenew: bool = False,
        region: Optional[str] = None,
        user_data: Optional[str] = None
    ) -> str:
        """Launch a new VPS server. Returns machine_id."""
        flavor = flavor or self.DEFAULT_FLAVOR
        operating_system = operating_system or self.DEFAULT_OS
        provider = provider or self.DEFAULT_PROVIDER
        days = days or self.DEFAULT_DAYS
        region = region or self.DEFAULT_REGION

        payload = {
            "flavor": flavor,
            "ssh_key": ssh_key,
            "operating_system": operating_system,
            "provider": provider,
            "days": days,
            "region": region,
        }

        if hostname:
            payload["hostname"] = hostname
        if autorenew:
            payload["autorenew"] = autorenew
        if user_data:
            payload["user_data"] = user_data

        logger.info(
            f"Launching server: {flavor} on {provider} "
            f"with {operating_system} for {days} days in {region}"
        )

        try:
            response = self._request(
                "POST",
                f"/token/{self.token}/servers",
                json=payload
            )
            machine_id = response.get("machine_id")
            logger.info(f"Server launched: {machine_id}")
            return machine_id

        except SporeStackError as e:
            if "insufficient" in str(e).lower():
                raise InsufficientBalanceError(str(e))
            raise

    def list_servers(self) -> List[Dict[str, Any]]:
        return self._request("GET", f"/token/{self.token}/servers")

    def get_server(self, machine_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/token/{self.token}/servers/{machine_id}")

    def delete_server(self, machine_id: str) -> bool:
        logger.info(f"Deleting server: {machine_id}")
        self._request("DELETE", f"/token/{self.token}/servers/{machine_id}")
        return True

    def start_server(self, machine_id: str) -> bool:
        self._request("POST", f"/token/{self.token}/servers/{machine_id}/start")
        return True

    def stop_server(self, machine_id: str) -> bool:
        self._request("POST", f"/token/{self.token}/servers/{machine_id}/stop")
        return True

    def reboot_server(self, machine_id: str) -> bool:
        self._request("POST", f"/token/{self.token}/servers/{machine_id}/reboot")
        return True

    def rebuild_server(self, machine_id: str) -> bool:
        self._request("POST", f"/token/{self.token}/servers/{machine_id}/rebuild")
        return True

    def topup_server(self, machine_id: str, days: int) -> bool:
        """Extend server lifetime by given days."""
        self._request(
            "POST",
            f"/token/{self.token}/servers/{machine_id}/topup",
            json={"days": days}
        )
        return True

    def wait_for_server_ready(
        self,
        machine_id: str,
        timeout: int = 300,
        poll_interval: int = 10
    ) -> Dict[str, Any]:
        """Wait for server to have an IPv4 address. Raises ServerNotReadyError on timeout."""
        logger.info(f"Waiting for server {machine_id} to be ready...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            server = self.get_server(machine_id)

            ipv4 = server.get("ipv4")
            if ipv4 and ipv4 != "0.0.0.0":
                logger.info(f"Server ready: {ipv4}")
                return server

            logger.debug(f"Server not ready yet, waiting {poll_interval}s...")
            time.sleep(poll_interval)

        raise ServerNotReadyError(
            f"Server {machine_id} not ready after {timeout}s"
        )

    def get_flavors(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/slugs/flavors")

    def get_operating_systems(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/slugs/os")

    def get_regions(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/slugs/regions")

    def get_quote(
        self,
        flavor: str,
        days: int,
        provider: str = "digitalocean"
    ) -> Dict[str, Any]:
        """Get price quote for a server configuration."""
        return self._request(
            "GET",
            "/server/quote",
            params={
                "flavor": flavor,
                "days": days,
                "provider": provider,
            }
        )


