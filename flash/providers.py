"""Read-only Solana/RugCheck/Jupiter evidence providers for paper trading.

This module never signs, builds, or submits transactions. Any upstream failure
returns incomplete evidence and is rejected by the engine's strict safety gate.
"""
from __future__ import annotations
import os
import time
import requests

SOL_MINT = "So11111111111111111111111111111111111111112"
RPC_DEFAULT = "https://api.mainnet.solana.com"
RUGCHECK_BASE = "https://api.rugcheck.xyz/v1"
JUPITER_ORDER = "https://api.jup.ag/swap/v2/order"

class SolanaTokenAssessor:
    def __init__(self, rpc_url=None, rugcheck_base=RUGCHECK_BASE,
                 jupiter_api_key=None, timeout=12, session=None):
        self.rpc_url = rpc_url or os.getenv("SOLANA_RPC_URL") or RPC_DEFAULT
        self.rugcheck_base = rugcheck_base.rstrip("/")
        self.jupiter_api_key = jupiter_api_key if jupiter_api_key is not None else os.getenv("JUPITER_API_KEY", "")
        self.timeout = timeout
        self.session = session or requests.Session()
        self._cache = {}
        self._last_jupiter_request = 0.0
        self.metrics = {"provider":"Solana RPC + RugCheck + Jupiter quote",
            "checks":0,"success":0,"failed":0,"last_success_at":None,
            "last_error":"","rpc":"configured" if self.rpc_url else "missing",
            "jupiter_auth":"api_key" if self.jupiter_api_key else "keyless_rate_limited"}

    def status(self):
        return dict(self.metrics)

    def _get(self, url, params=None, headers=None):
        response = self.session.get(url, params=params, headers=headers or {}, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Provider returned a non-object response")
        return data

    def _rpc(self, method, params):
        response = self.session.post(self.rpc_url, json={
            "jsonrpc":"2.0","id":1,"method":method,"params":params
        }, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("error") or "result" not in payload:
            raise ValueError("Solana RPC error for " + method)
        return payload["result"]

    def _mint_data(self, mint):
        result = self._rpc("getAccountInfo", [mint, {"encoding":"jsonParsed","commitment":"confirmed"}])
        value = (result or {}).get("value")
        if not isinstance(value, dict):
            raise ValueError("Mint account not found")
        parsed = ((value.get("data") or {}).get("parsed") or {})
        info = parsed.get("info")
        if not isinstance(info, dict) or parsed.get("type") != "mint":
            raise ValueError("Mint account was not parsed as a supported mint")
        extensions = info.get("extensions") or []
        # Strict policy: refuse unknown Token-2022 extensions until explicitly audited.
        if extensions:
            raise ValueError("Token-2022 mint extensions require explicit review")
        decimals = int(info["decimals"])
        supply = int(info["supply"])
        if decimals < 0 or decimals > 18 or supply <= 0:
            raise ValueError("Invalid mint decimals or supply")
        return {"mint_authority":info.get("mintAuthority"),
                "freeze_authority":info.get("freezeAuthority"),
                "decimals":decimals,"supply":supply,
                "token_program":value.get("owner")}

    def _concentration(self, mint, supply):
        result = self._rpc("getTokenLargestAccounts", [mint, {"commitment":"confirmed"}])
        values = (result or {}).get("value")
        if not isinstance(values, list) or not values:
            raise ValueError("Largest token-account data unavailable")
        accounts = values[:10]
        addresses = [item.get("address") for item in accounts if item.get("address")]
        if len(addresses) != len(accounts):
            raise ValueError("Largest token-account addresses incomplete")
        owners_result = self._rpc("getMultipleAccounts", [
            addresses, {"encoding":"jsonParsed","commitment":"confirmed"}
        ])
        owner_values = (owners_result or {}).get("value")
        if not isinstance(owner_values, list) or len(owner_values) != len(accounts):
            raise ValueError("Token-account owner details unavailable")
        balances_by_owner = {}
        for account, owner_account in zip(accounts, owner_values):
            parsed_info = (((owner_account or {}).get("data") or {}).get("parsed") or {}).get("info") or {}
            owner = parsed_info.get("owner")
            if not owner:
                raise ValueError("Token-account owner missing")
            balances_by_owner[owner] = balances_by_owner.get(owner, 0) + int(account["amount"])
        top10_holders = sorted(balances_by_owner.values(), reverse=True)[:10]
        return min(100.0, sum(top10_holders) / supply * 100.0)

    def _rugcheck(self, mint):
        report = self._get(f"{self.rugcheck_base}/tokens/{mint}/report/summary")
        risks = report.get("risks")
        if not isinstance(risks, list):
            raise ValueError("RugCheck risks missing or malformed")
        critical, warnings = [], []
        for risk in risks:
            if not isinstance(risk, dict):
                critical.append("malformed_risk_record")
                continue
            level = str(risk.get("level", "")).strip().lower()
            name = str(risk.get("name") or "unnamed_risk")
            if level in {"danger","critical","high"}:
                critical.append(name)
            elif level == "warn":
                warnings.append(name)
            elif level not in {"", "info", "good", "low"}:
                critical.append("unknown_risk_level:" + level)
        return ("warn" if warnings and not critical else "good" if not critical else "danger",
                critical, warnings, report.get("tokenProgram"))

    def _sell_quote(self, mint, decimals, price_usd, notional_usd):
        if price_usd <= 0 or notional_usd <= 0:
            raise ValueError("Invalid simulated quote size or token price")
        raw_amount = int(notional_usd / price_usd * (10 ** decimals))
        if raw_amount <= 0:
            raise ValueError("Quote amount rounds to zero")
        headers = {"x-api-key":self.jupiter_api_key} if self.jupiter_api_key else {}
        min_interval = 1.1 if self.jupiter_api_key else 2.1
        wait = min_interval - (time.monotonic() - self._last_jupiter_request)
        if wait > 0:
            time.sleep(wait)
        self._last_jupiter_request = time.monotonic()
        data = self._get(JUPITER_ORDER, params={
            "inputMint":mint,"outputMint":SOL_MINT,"amount":str(raw_amount)
        }, headers=headers)
        if data.get("error") or not data.get("outAmount") or not data.get("routePlan"):
            raise ValueError("Jupiter returned no verified sell route")
        impact_raw = data.get("priceImpactPct")
        if impact_raw is None:
            raise ValueError("Jupiter quote did not include price impact")
        impact = float(impact_raw) * 100.0
        if not 0 <= impact <= 100:
            raise ValueError("Jupiter quote returned invalid price impact")
        return impact, raw_amount, data.get("router") or data.get("swapType") or "Jupiter"

    def assess(self, snapshot, now, notional_usd):
        mint = str(snapshot.get("address") or "").strip()
        if not mint:
            raise ValueError("Token mint address missing")
        key = (mint, round(float(notional_usd), 2))
        cached = self._cache.get(key)
        if cached and float(now) - cached["checked_at"] <= 15:
            return dict(cached)
        self.metrics["checks"] += 1
        try:
            mint_data = self._mint_data(mint)
            concentration = self._concentration(mint, mint_data["supply"])
            rug_status, critical, warnings, token_program = self._rugcheck(mint)
            impact, raw_amount, router = self._sell_quote(
                mint, mint_data["decimals"], float(snapshot.get("price") or 0), float(notional_usd))
            evidence = {
                "mint_authority":mint_data["mint_authority"],
                "freeze_authority":mint_data["freeze_authority"],
                "top10_holder_pct":concentration,
                "rugcheck_status":rug_status,
                "critical_risks":critical,
                "sell_route_available":True,
                "checked_at":float(now),
                "execution_impact_pct":impact,
                "token_program":token_program or mint_data["token_program"],
                "top10_token_account_pct":concentration,
                "rugcheck_warnings":warnings,
                "quote_amount_raw":str(raw_amount),
                "quote_router":router,
                "provider_checked_at":float(now),
            }
            self.metrics["success"] += 1
            self.metrics["last_success_at"] = float(now)
            self.metrics["last_error"] = ""
            self._cache[key] = dict(evidence)
            # Keep memory bounded.
            if len(self._cache) > 500:
                self._cache = {k:v for k,v in self._cache.items() if float(now)-v["checked_at"] <= 300}
            return evidence
        except (requests.RequestException, ValueError, KeyError, TypeError, OverflowError) as exc:
            self.metrics["failed"] += 1
            self.metrics["last_error"] = str(exc)[:240]
            raise
