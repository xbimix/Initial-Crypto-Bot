from __future__ import annotations

import hmac
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class MutatingSafetyMiddleware:
    get_mutating_endpoints: Callable[[], set[str]]
    get_local_loopbacks: Callable[[], set[str]]
    allow_non_local_requests: Callable[[], bool]
    get_payload_max_bytes: Callable[[], int]
    get_rate_limit_window_seconds: Callable[[], int]
    get_rate_limit_max_requests: Callable[[], int]
    resolve_arming_contract: Callable[[], object]
    resolve_expected_auth_token: Callable[[], str]
    json_error: Callable[..., object]
    rate_limit_buckets: dict[str, deque[float]]

    def is_mutating_request(self, request) -> bool:
        method = str(getattr(request, "method", "") or "").upper()
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return False
        path = getattr(request, "path", "") or ""
        return path in self.get_mutating_endpoints()

    def extract_client_ip(self, request) -> str:
        access_route = getattr(request, "access_route", None)
        if access_route:
            route_ip = str(access_route[0] or "").strip()
            if route_ip:
                return route_ip
        remote = str(getattr(request, "remote_addr", "") or "").strip()
        return remote

    def is_local_request(self, request) -> bool:
        client_ip = self.extract_client_ip(request).lower()
        if not client_ip:
            return False
        if client_ip in self.get_local_loopbacks():
            return True
        if client_ip.startswith("127."):
            return True
        return False

    def extract_auth_token(self, request) -> str:
        headers = getattr(request, "headers", {})
        bearer = str(headers.get("Authorization", "") or "").strip()
        if bearer.lower().startswith("bearer "):
            return bearer[7:].strip()
        direct = str(headers.get("X-Revbot-Token", "") or "").strip()
        if direct:
            return direct
        return ""

    def extract_actor(self, request) -> str:
        headers = getattr(request, "headers", {})
        actor = str(headers.get("X-Revbot-Actor", "") or "").strip()
        if actor:
            return actor
        ip = self.extract_client_ip(request)
        if ip:
            return f"ip:{ip}"
        return "unknown"

    def check_payload_size(self, request):
        if not self.is_mutating_request(request):
            return None
        max_bytes = int(self.get_payload_max_bytes())
        content_length = getattr(request, "content_length", None)
        if content_length is not None and content_length > max_bytes:
            return self.json_error(
                "Payload too large",
                status=413,
                code="payload_too_large",
                details={"max_bytes": max_bytes},
            )
        if content_length is None:
            payload = request.get_data(cache=True, as_text=False)
            if len(payload) > max_bytes:
                return self.json_error(
                    "Payload too large",
                    status=413,
                    code="payload_too_large",
                    details={"max_bytes": max_bytes},
                )
        return None

    def check_rate_limit(self, request):
        if not self.is_mutating_request(request):
            return None
        client_ip = self.extract_client_ip(request) or "unknown"
        bucket_key = f"{client_ip}:{request.path}"
        now = time.time()
        window_seconds = int(self.get_rate_limit_window_seconds())
        max_requests = int(self.get_rate_limit_max_requests())
        window_start = now - window_seconds

        bucket = self.rate_limit_buckets[bucket_key]
        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= max_requests:
            return self.json_error(
                "Too many requests",
                status=429,
                code="rate_limited",
                details={
                    "limit": max_requests,
                    "window_seconds": window_seconds,
                },
            )
        bucket.append(now)
        return None

    def check_mutating_auth(self, request):
        if not self.is_mutating_request(request):
            return None
        contract = self.resolve_arming_contract()
        if not bool(getattr(contract, "mutating_allowed", False)):
            failures = set(getattr(contract, "failures", ()) or ())
            if "missing_auth_token" in failures:
                return self.json_error(
                    "Mutating auth token is not configured",
                    status=503,
                    code="auth_not_configured",
                )
            if "strict_mutating_auth_disabled" in failures:
                return self.json_error(
                    "Deployed mode requires REVBOT_STRICT_MUTATING_AUTH=true",
                    status=503,
                    code="mutating_contract_blocked",
                    details={"failures": list(getattr(contract, "failures", ()) or ())},
                )
            if "deployed_mutations_not_enabled" in failures:
                return self.json_error(
                    "Deployed mode mutating routes require REVBOT_ALLOW_DEPLOYED_MUTATIONS=true",
                    status=503,
                    code="mutating_contract_blocked",
                    details={"failures": list(getattr(contract, "failures", ()) or ())},
                )
            return self.json_error(
                "Mutating control contract blocked",
                status=503,
                code="mutating_contract_blocked",
                details={"failures": list(getattr(contract, "failures", ()) or ())},
            )

        expected = self.resolve_expected_auth_token()
        provided = self.extract_auth_token(request)
        if not provided or not hmac.compare_digest(provided, expected):
            return self.json_error(
                "Unauthorized",
                status=401,
                code="unauthorized",
            )
        return None

    def enforce(self, request, g):
        if not self.is_mutating_request(request):
            return None

        setattr(g, "revbot_actor", self.extract_actor(request))
        if not self.allow_non_local_requests() and not self.is_local_request(request):
            return self.json_error(
                "Non-local requests are not allowed",
                status=403,
                code="non_local_forbidden",
            )

        payload_check = self.check_payload_size(request)
        if payload_check is not None:
            return payload_check
        auth_check = self.check_mutating_auth(request)
        if auth_check is not None:
            return auth_check
        rate_check = self.check_rate_limit(request)
        if rate_check is not None:
            return rate_check
        return None

