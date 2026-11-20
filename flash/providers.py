"""Read-only Solana/RugCheck/Jupiter evidence providers for paper trading.

Uses public Solana mainnet-beta RPC and Jupiter's read-only quote endpoint.
No wallet, signing, transaction construction, or swap submission exists here.
Any incomplete provider evidence fails closed.
"""
from __future__ import annotations

import os
import time
import requests

SOL_MINT = "So11111111111111111111111111111111111111112"
RPC_DEFAULT = "https://solana-rpc.publicnode.com"
RPC_FALLBACKS = ("https://api.mainnet-beta.solana.com",)
RUGCHECK_BASE = "https://api.rugcheck.xyz/v1"
JUPITER_LITE_QUOTE = "https://lite-api.jup.ag/swap/v1/quote"
JUPITER_PAID_QUOTE = "https://api.jup.ag/swap/v1/quote"


class SolanaTokenAssessor:
    def __init__(self, rpc_url=None, rugcheck_base=RUGCHECK_BASE,
                 jupiter_api_key=None, timeout=7, session=None):
        configured_rpc = rpc_url or os.getenv("SOLANA_RPC_URL") or RPC_DEFAULT
        configured_fallbacks = os.getenv("SOLANA_RPC_FALLBACK_URLS", "")
        fallbacks = [item.strip() for item in configured_fallbacks.split(",") if item.strip()]
        fallbacks.extend(RPC_FALLBACKS)
        self.rpc_endpoints = list(dict.fromkeys([configured_rpc, *fallbacks]))
        self.rpc_url = self.rpc_endpoints[0]
        self._rpc_cooldowns = {}
        self._failure_cache = {}
        self.rugcheck_base = rugcheck_base.rstrip("/")
        self.jupiter_api_key = (jupiter_api_key if jupiter_api_key is not None
                                else os.getenv("JUPITER_API_KEY", ""))
        self.jupiter_url = JUPITER_PAID_QUOTE if self.jupiter_api_key else JUPITER_LITE_QUOTE
        self.timeout = max(3, min(int(timeout), 10))
        self.session = session or requests.Session()
        self._cache = {}
        self.metrics = {
            "provider": "Solana RPC + RugCheck + Jupiter read-only quote",
            "status": "ready", "checks": 0, "success": 0, "failed": 0,
            "last_attempt_at": None, "last_success_at": None, "last_error": "",
            "last_failed_stage": "", "rpc_success": 0, "rpc_failed": 0,
            "rugcheck_success": 0, "rugcheck_failed": 0,
            "jupiter_success": 0, "jupiter_failed": 0,
            "rpc_endpoint": self.rpc_url, "rpc_endpoints_configured": len(self.rpc_endpoints),
            "rpc_requests": 0, "rpc_fallbacks": 0, "rpc_cooldowns": 0,
            "rpc_last_http_status": None, "rpc_last_error": "",
            "assessment_cooldowns": 0,
            "jupiter_endpoint": self.jupiter_url,
            "jupiter_auth": "api_key" if self.jupiter_api_key else "public_lite_api",
        }

    def status(self):
        return dict(self.metrics)

    def _get(self, url, params=None, headers=None):
        response = self.session.get(url, params=params, headers=headers or {},
                                    timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Provider returned a non-object response")
        return data

    def _rpc(self, method, params):
        now = time.time()
        errors = []
        available = [url for url in self.rpc_endpoints
                     if self._rpc_cooldowns.get(url, 0) <= now]
        if not available:
            available = [min(self.rpc_endpoints,
                             key=lambda url: self._rpc_cooldowns.get(url, 0))]
        for index, endpoint in enumerate(available):
            self.metrics["rpc_requests"] += 1
            try:
                response = self.session.post(endpoint, json={
                    "jsonrpc": "2.0", "id": 1, "method": method, "params": params
                }, timeout=self.timeout)
                status = getattr(response, "status_code", None)
                self.metrics["rpc_last_http_status"] = status
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("error") or "result" not in payload:
                    detail = payload.get("error") if isinstance(payload, dict) else None
                    raise ValueError("Solana RPC " + method + " failed: " +
                                     str(detail or "invalid response")[:140])
                self.rpc_url = endpoint
                self.metrics["rpc_endpoint"] = endpoint
                self.metrics["rpc_success"] += 1
                self.metrics["rpc_last_error"] = ""
                if index:
                    self.metrics["rpc_fallbacks"] += 1
                return payload["result"]
            except requests.RequestException as exc:
                response_obj = getattr(exc, "response", None)
                status = getattr(response_obj, "status_code", None)
                self.metrics["rpc_last_http_status"] = status or self.metrics.get("rpc_last_http_status")
                errors.append(f"{endpoint}: {str(exc)[:160]}")
                if status == 429:
                    retry_after = getattr(response_obj, "headers", {}).get("Retry-After")
                    try:
                        cooldown = max(10, min(int(float(retry_after)), 180)) if retry_after else 30
                    except (TypeError, ValueError):
                        cooldown = 30
                    self._rpc_cooldowns[endpoint] = now + cooldown
                    self.metrics["rpc_cooldowns"] += 1
                continue
            except ValueError as exc:
                errors.append(f"{endpoint}: {str(exc)[:160]}")
                continue
        self.metrics["rpc_last_error"] = " | ".join(errors)[-400:]
        raise requests.RequestException(
            f"All configured Solana RPC endpoints failed for {method}: " +
            self.metrics["rpc_last_error"])

    def _mint_data(self, mint):
        result = self._rpc("getAccountInfo", [
            mint, {"encoding": "jsonParsed", "commitment": "confirmed"}
        ])
        value = (result or {}).get("value")
        if not isinstance(value, dict):
            raise ValueError("Mint account not found on Solana mainnet")
        parsed = ((value.get("data") or {}).get("parsed") or {})
        info = parsed.get("info")
        if not isinstance(info, dict) or parsed.get("type") != "mint":
            raise ValueError("Mint account is not a supported parsed SPL mint")
        extensions = info.get("extensions") or []
        if extensions:
            raise ValueError("Token-2022 mint extensions require explicit review")
        decimals, supply = int(info["decimals"]), int(info["supply"])
        if decimals < 0 or decimals > 18 or supply <= 0:
            raise ValueError("Invalid mint decimals or supply")
        return {
            "mint_authority": info.get("mintAuthority"),
            "freeze_authority": info.get("freezeAuthority"),
            "decimals": decimals, "supply": supply,
            "token_program": value.get("owner"),
        }

    def _concentration(self, mint, supply):
        result = self._rpc("getTokenLargestAccounts", [
            mint, {"commitment": "confirmed"}
        ])
        values = (result or {}).get("value")
        if not isinstance(values, list) or not values:
            raise ValueError("Largest token-account data unavailable")
        accounts = values[:10]
        addresses = [item.get("address") for item in accounts if item.get("address")]
        if len(addresses) != len(accounts):
            raise ValueError("Largest token-account addresses incomplete")
        owners_result = self._rpc("getMultipleAccounts", [
            addresses, {"encoding": "jsonParsed", "commitment": "confirmed"}
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
        # This is an estimate based on the ten largest token accounts, not a
        # full holder census. Multiple accounts owned by one wallet are grouped.
        return min(100.0, sum(sorted(balances_by_owner.values(), reverse=True)[:10]) / supply * 100.0)

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
            if level in {"danger", "critical", "high"}:
                critical.append(name)
            elif level == "warn":
                warnings.append(name)
            elif level not in {"", "info", "good", "low"}:
                critical.append("unknown_risk_level:" + level)
        self.metrics["rugcheck_success"] += 1
        return ("warn" if warnings and not critical else "good" if not critical else "danger",
                critical, warnings, report.get("tokenProgram"))

    def _sell_quote(self, mint, decimals, price_usd, notional_usd):
        if price_usd <= 0 or notional_usd <= 0:
            raise ValueError("Invalid simulated quote size or token price")
        raw_amount = int(notional_usd / price_usd * (10 ** decimals))
        if raw_amount <= 0:
            raise ValueError("Quote amount rounds to zero")
        headers = {"x-api-key": self.jupiter_api_key} if self.jupiter_api_key else {}
        data = self._get(self.jupiter_url, params={
            "inputMint": mint, "outputMint": SOL_MINT,
            "amount": str(raw_amount), "slippageBps": "100",
        }, headers=headers)
        if (data.get("error") or data.get("inputMint") != mint
                or data.get("outputMint") != SOL_MINT
                or int(data.get("inAmount") or 0) != raw_amount
                or int(data.get("outAmount") or 0) <= 0
                or not isinstance(data.get("routePlan"), list)
                or not data["routePlan"]):
            raise ValueError("Jupiter quote missing a matching executable route")
        impact_raw = data.get("priceImpactPct")
        if impact_raw is None:
            raise ValueError("Jupiter quote did not include price impact")
        impact = float(impact_raw) * 100.0
        if not 0 <= impact <= 100:
            raise ValueError("Jupiter quote returned invalid price impact")
        self.metrics["jupiter_success"] += 1
        return impact, raw_amount, data.get("router") or data.get("swapType") or "Jupiter quote API"

    def assess(self, snapshot, now, notional_usd):
        mint = str(snapshot.get("address") or "").strip()
        if not mint:
            raise ValueError("Token mint address missing")
        key = (mint, round(float(notional_usd), 2),
               format(float(snapshot.get("price") or 0), ".12g"))
        cached = self._cache.get(key)
        if cached and float(now) - cached["checked_at"] <= 15:
            return dict(cached)
        failed = self._failure_cache.get(mint)
        if failed and float(now) - failed["failed_at"] < 30:
            self.metrics["assessment_cooldowns"] += 1
            raise ValueError("Assessment temporarily paused after recent provider failure: " +
                             failed["error"][:160])

        self.metrics["checks"] += 1
        self.metrics["last_attempt_at"] = float(now)
        stage = "solana_rpc"
        try:
            mint_data = self._mint_data(mint)
            concentration = self._concentration(mint, mint_data["supply"])
            stage = "rugcheck"
            rug_status, critical, warnings, token_program = self._rugcheck(mint)
            stage = "jupiter_quote"
            impact, raw_amount, router = self._sell_quote(
                mint, mint_data["decimals"], float(snapshot.get("price") or 0),
                float(notional_usd))
            evidence = {
                "mint_authority": mint_data["mint_authority"],
                "freeze_authority": mint_data["freeze_authority"],
                "top10_holder_pct": concentration,
                "rugcheck_status": rug_status, "critical_risks": critical,
                "sell_route_available": True, "checked_at": float(now),
                "execution_impact_pct": impact,
                "token_program": token_program or mint_data["token_program"],
                "top10_token_account_pct": concentration,
                "rugcheck_warnings": warnings, "quote_amount_raw": str(raw_amount),
                "quote_router": router, "provider_checked_at": float(now),
            }
            self.metrics["success"] += 1
            self.metrics["status"] = "healthy"
            self.metrics["last_success_at"] = float(now)
            self.metrics["last_error"] = ""
            self.metrics["last_failed_stage"] = ""
            self._cache[key] = dict(evidence)
            self._failure_cache.pop(mint, None)
            if len(self._cache) > 500:
                self._cache = {k: v for k, v in self._cache.items()
                               if float(now) - v["checked_at"] <= 300}
            if len(self._failure_cache) > 500:
                self._failure_cache = {k: v for k, v in self._failure_cache.items()
                                       if float(now) - v["failed_at"] <= 60}
            return evidence
        except requests.RequestException as exc:
            self.metrics["failed"] += 1
            self.metrics["status"] = "degraded"
            self.metrics["last_failed_stage"] = stage
            self.metrics["last_error"] = f"{stage}: {str(exc)[:200]}"
            self._failure_cache[mint] = {"failed_at": float(now), "error": self.metrics["last_error"]}
            if stage == "rugcheck":
                self.metrics["rugcheck_failed"] += 1
            elif stage == "jupiter_quote":
                self.metrics["jupiter_failed"] += 1
            else:
                self.metrics["rpc_failed"] += 1
            raise
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            self.metrics["failed"] += 1
            self.metrics["status"] = "degraded"
            self.metrics["last_failed_stage"] = stage
            self.metrics["last_error"] = f"{stage}: {str(exc)[:200]}"
            self._failure_cache[mint] = {"failed_at": float(now), "error": self.metrics["last_error"]}
            if stage == "rugcheck":
                self.metrics["rugcheck_failed"] += 1
            elif stage == "jupiter_quote":
                self.metrics["jupiter_failed"] += 1
            else:
                self.metrics["rpc_failed"] += 1
            raise
