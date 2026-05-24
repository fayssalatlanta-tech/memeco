import os
from typing import Any

import httpx
from dotenv import load_dotenv


load_dotenv()


class HeliusClient:
    BASE_URL = "https://api-mainnet.helius-rpc.com"
    RPC_BASE_URL = "https://mainnet.helius-rpc.com"

    def __init__(self) -> None:
        self.api_key = os.getenv("HELIUS_API_KEY")
        self.timeout = httpx.Timeout(20.0)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def get_address_transactions(
        self,
        address: str,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("HELIUS_API_KEY is missing. Check your .env file.")

        url = f"{self.BASE_URL}/v0/addresses/{address}/transactions"
        params = {
            "api-key": self.api_key,
            "limit": limit,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        return data if isinstance(data, list) else []

    async def rpc(self, method: str, params: list[Any]) -> Any:
        if not self.api_key:
            raise RuntimeError("HELIUS_API_KEY is missing. Check your .env file.")

        url = f"{self.RPC_BASE_URL}/?api-key={self.api_key}"
        payload = {
            "jsonrpc": "2.0",
            "id": "quant-platform",
            "method": method,
            "params": params,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        if data.get("error"):
            raise RuntimeError(f"Helius RPC error for {method}: {data['error']}")

        return data.get("result")

    async def get_signatures_for_address(
        self,
        address: str,
        limit: int = 100,
        before: str | None = None,
    ) -> list[dict[str, Any]]:
        config: dict[str, Any] = {"limit": limit}
        if before:
            config["before"] = before

        result = await self.rpc("getSignaturesForAddress", [address, config])
        return result if isinstance(result, list) else []

    async def get_enhanced_transactions(
        self,
        signatures: list[str],
    ) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("HELIUS_API_KEY is missing. Check your .env file.")

        if not signatures:
            return []

        url = f"{self.BASE_URL}/v0/transactions"
        params = {"api-key": self.api_key}
        payload = {"transactions": signatures[:100]}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, params=params, json=payload)
            response.raise_for_status()
            data = response.json()

        return data if isinstance(data, list) else []

    async def get_webhooks(self) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("HELIUS_API_KEY is missing. Check your .env file.")

        url = f"{self.BASE_URL}/v0/webhooks"
        params = {"api-key": self.api_key}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        return data if isinstance(data, list) else []

    async def create_webhook(
        self,
        webhook_url: str,
        account_addresses: list[str],
        transaction_types: list[str] | None = None,
        auth_header: str | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("HELIUS_API_KEY is missing. Check your .env file.")

        url = f"{self.BASE_URL}/v0/webhooks"
        params = {"api-key": self.api_key}
        payload: dict[str, Any] = {
            "webhookURL": webhook_url,
            "transactionTypes": transaction_types or ["SWAP"],
            "accountAddresses": account_addresses,
            "webhookType": "enhanced",
            "txnStatus": "success",
        }
        if auth_header:
            payload["authHeader"] = auth_header

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, params=params, json=payload)
            response.raise_for_status()
            return response.json()

    async def update_webhook(
        self,
        webhook_id: str,
        webhook_url: str,
        account_addresses: list[str],
        transaction_types: list[str] | None = None,
        auth_header: str | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("HELIUS_API_KEY is missing. Check your .env file.")

        url = f"{self.BASE_URL}/v0/webhooks/{webhook_id}"
        params = {"api-key": self.api_key}
        payload: dict[str, Any] = {
            "webhookURL": webhook_url,
            "transactionTypes": transaction_types or ["SWAP"],
            "accountAddresses": account_addresses,
            "webhookType": "enhanced",
            "txnStatus": "success",
        }
        if auth_header:
            payload["authHeader"] = auth_header

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.put(url, params=params, json=payload)
            response.raise_for_status()
            return response.json()
