"""CapForge High-Level Python SDK Client.

Provides a unified, batteries-included entry point for developers integrating
CapForge into their existing AI agent systems. Designed for both local (embedded)
and remote (client-server) usage patterns.

Usage:
    from capforge import CapForgeClient, capability

    # Decorator-based registration
    @capability(id="my_tool", domain="nlp")
    def analyze(text: str) -> dict:
        return {"sentiment": "positive"}

    # High-level client (embedded local mode)
    with CapForgeClient() as client:
        client.register(analyze, promote=True)
        result = client.execute("my_tool", {"text": "hello"})
        print(result.output)

    # Remote mode (connecting to CapForge REST API server)
    client = CapForgeClient(server_url="http://localhost:8000", api_key="secret")
    client.health_check()
"""

from __future__ import annotations

import functools
import inspect
import logging
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

from capforge.core.models import (
    Capability,
    CapabilityStatus,
    CapabilityType,
    ExecutionMode,
    ExecutionRequest,
    ExecutionResponse,
    ParameterSpec,
    RiskLevel,
    TestCase,
    TestType,
    ToolPermissions,
    VerificationResult,
)
from capforge.events.webhooks import (
    WebhookDelivery,
    WebhookSubscription,
    webhook_manager,
)
from capforge.registry.store import CapabilityRegistry
from capforge.runtime.agent_adapter import AgentLifecycleTrace, CapForgeAgent
from capforge.runtime.executor import CapabilityExecutor
from capforge.security.code_guardian import CodeGuardian
from capforge.security.trust_chain import TrustChain
from capforge.verification.evaluator import CapabilityEvaluator

logger = logging.getLogger("capforge.sdk")

_PYTHON_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    dict: "object",
    list: "array",
    tuple: "array",
    set: "array",
    bytes: "string",
}


def _resolve_type_name(annotation: Any) -> str:
    """Map a Python type annotation to CapForge parameter type string."""
    if annotation is inspect.Parameter.empty:
        return "string"
    origin = getattr(annotation, "__origin__", None)
    if origin is not None:
        if origin in (list, tuple, set, frozenset):
            return "array"
        if origin is dict:
            return "object"
    if isinstance(annotation, type) and annotation in _PYTHON_TYPE_MAP:
        return _PYTHON_TYPE_MAP[annotation]
    return "string"


def capability(
    id: str | None = None,
    name: str | None = None,
    domain: str = "general",
    risk_level: str = "LOW",
    tags: list[str] | None = None,
    version: str = "1.0.0",
    permissions: dict[str, str] | None = None,
    tests: list[dict[str, Any]] | None = None,
    status: CapabilityStatus = CapabilityStatus.EXPERIMENTAL,
    namespace: str = "default",
) -> Callable:
    """Decorator that converts a Python function into a CapForge Capability.

    The decorated function retains its original behavior when called directly,
    but gains .capforge_capability and .to_tool() attributes.
    """

    def decorator(func: Callable) -> Callable:
        cap_id = id or func.__name__
        cap_name = name or func.__name__.replace("_", " ").title()
        description = inspect.getdoc(func) or f"Capability: {cap_name}"

        sig = inspect.signature(func)
        inputs: dict[str, ParameterSpec] = {}
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue
            has_default = param.default is not inspect.Parameter.empty
            inputs[param_name] = ParameterSpec(
                name=param_name,
                type=_resolve_type_name(param.annotation),
                description=f"Parameter {param_name}",
                required=not has_default,
                default=param.default if has_default else None,
            )

        outputs: dict[str, ParameterSpec] = {}
        return_annotation = sig.return_annotation
        if return_annotation is not inspect.Signature.empty:
            outputs["result"] = ParameterSpec(
                name="result",
                type=_resolve_type_name(return_annotation),
                description="Function return value",
            )

        try:
            raw_source = textwrap.dedent(inspect.getsource(func))
            lines = raw_source.splitlines()
            def_idx = 0
            for idx, line in enumerate(lines):
                if line.startswith("def ") or line.startswith("async def "):
                    def_idx = idx
                    break
            source = "\n".join(lines[def_idx:]) + "\n"
        except (OSError, TypeError):
            source = f"def {func.__name__}(**kwargs):\n    return kwargs\n"

        verification_tests: list[TestCase] = []
        for i, test_def in enumerate(tests or []):
            verification_tests.append(
                TestCase(
                    id=test_def.get("id", f"auto_test_{i + 1}"),
                    name=test_def.get("name", f"Auto test {i + 1}"),
                    test_type=(
                        TestType[test_def["test_type"].upper()]
                        if "test_type" in test_def and hasattr(TestType, test_def["test_type"].upper())
                        else TestType.SMOKE
                    ),
                    inputs=test_def.get("inputs", {}),
                    expected_keys=test_def.get("expected_keys"),
                    expected_output_contains=test_def.get("expected_output_contains"),
                    assert_expression=test_def.get("assert_expression"),
                )
            )

        perm = ToolPermissions()
        if permissions:
            perm = ToolPermissions(**permissions)

        try:
            resolved_risk = RiskLevel(risk_level.upper())
        except ValueError:
            resolved_risk = RiskLevel.LOW

        cap = Capability(
            id=cap_id,
            name=cap_name,
            version=version,
            namespace=namespace,
            description=description,
            domain=domain,
            tags=tags or [],
            risk_level=resolved_risk,
            permissions=perm,
            inputs=inputs,
            outputs=outputs,
            code_body=source,
            entrypoint_function=func.__name__,
            verification_tests=verification_tests,
            capability_type=CapabilityType.SKILL,
            status=status,
            changelog="Created via @capability decorator",
        )

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        wrapper.capforge_capability = cap
        wrapper.capforge_id = cap_id
        wrapper.to_tool = cap.to_tool
        wrapper.to_openai_tool = cap.to_openai_tool
        return wrapper

    return decorator


def capability_from_function(
    func: Callable,
    id: str | None = None,
    domain: str = "general",
    risk_level: str = "LOW",
    **kwargs: Any,
) -> Capability:
    """Create a Capability from a Python function without the decorator."""
    decorated = capability(id=id, domain=domain, risk_level=risk_level, **kwargs)(func)
    return decorated.capforge_capability


class CapForgeClient:
    """High-level SDK client for CapForge integration.

    Provides a single entry point for all CapForge operations in both local
    embedded and remote REST server modes.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        enable_trust_chain: bool = False,
        enable_security_scan: bool = True,
        auto_evaluate: bool = True,
        server_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        self._db_path = Path(db_path) if db_path else None
        self._server_url = server_url.rstrip("/") if server_url else None
        self._api_key = api_key
        self._timeout = timeout
        self._enable_trust_chain = enable_trust_chain
        self._enable_security_scan = enable_security_scan
        self._auto_evaluate = auto_evaluate

        self._registry: CapabilityRegistry | None = None
        self._agent: CapForgeAgent | None = None
        self._evaluator: CapabilityEvaluator | None = None
        self._guardian: CodeGuardian | None = None
        self._trust_chain: TrustChain | None = None
        self._executor: CapabilityExecutor | None = None
        self._http_client: Any | None = None

    @property
    def is_remote(self) -> bool:
        return self._server_url is not None

    def _get_http_client(self) -> Any:
        if self._http_client is None:
            import httpx

            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
                headers["X-API-Key"] = self._api_key
            self._http_client = httpx.Client(
                base_url=self._server_url,
                headers=headers,
                timeout=self._timeout,
            )
        return self._http_client

    @property
    def registry(self) -> CapabilityRegistry:
        if self._registry is None:
            self._registry = CapabilityRegistry(db_path=self._db_path) if self._db_path else CapabilityRegistry()
        return self._registry

    @property
    def agent(self) -> CapForgeAgent:
        if self._agent is None:
            self._agent = CapForgeAgent(registry=self.registry)
        return self._agent

    @property
    def evaluator(self) -> CapabilityEvaluator:
        if self._evaluator is None:
            self._evaluator = CapabilityEvaluator()
        return self._evaluator

    @property
    def executor(self) -> CapabilityExecutor:
        if self._executor is None:
            self._executor = CapabilityExecutor(
                registry=self.registry,
                trust_chain=self.trust_chain if self._enable_trust_chain else None,
            )
        return self._executor

    @property
    def guardian(self) -> CodeGuardian:
        if self._guardian is None:
            self._guardian = CodeGuardian(block_on_critical=True)
        return self._guardian

    @property
    def trust_chain(self) -> TrustChain:
        if self._trust_chain is None:
            trust_db = (self._db_path.parent / "trust.db") if self._db_path else None
            self._trust_chain = TrustChain(db_path=trust_db)
        return self._trust_chain

    @property
    def webhooks(self) -> Any:
        return webhook_manager

    def __enter__(self) -> CapForgeClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._http_client is not None:
            try:
                self._http_client.close()
            except Exception:
                pass
            self._http_client = None

    def register(
        self,
        cap_or_func: Capability | Callable,
        *,
        evaluate: bool | None = None,
        sign: bool | None = None,
        promote: bool = False,
    ) -> Capability:
        if callable(cap_or_func) and hasattr(cap_or_func, "capforge_capability"):
            cap = cap_or_func.capforge_capability
        elif isinstance(cap_or_func, Capability):
            cap = cap_or_func
        elif callable(cap_or_func):
            cap = capability_from_function(cap_or_func)
        else:
            raise TypeError(f"Expected Capability or callable, got {type(cap_or_func).__name__}")

        if self.is_remote:
            client = self._get_http_client()
            if promote:
                cap.status = CapabilityStatus.ACTIVE
            resp = client.post("/v1/capabilities/register", json=cap.model_dump(mode="json"))
            resp.raise_for_status()
            return Capability.model_validate(resp.json())

        if self._enable_security_scan:
            scan = self.guardian.scan(cap.id, cap.code_body)
            if scan.blocked:
                raise SecurityError(
                    f"Security scan blocked capability {cap.id}: {scan.critical_count} critical violations. {scan.summary}"
                )

        should_evaluate = evaluate if evaluate is not None else self._auto_evaluate
        verification = None
        if should_evaluate and cap.verification_tests:
            verification = self.evaluator.evaluate(cap)

        if promote and (verification is None or verification.passed):
            cap.status = CapabilityStatus.ACTIVE

        registered = self.registry.register(cap)
        should_sign = sign if sign is not None else self._enable_trust_chain
        if should_sign:
            self.trust_chain.sign(registered)

        try:
            self.webhooks.dispatch(
                "capability_registered",
                {"capability_id": registered.id, "version": registered.version, "status": registered.status.value},
            )
        except Exception:
            pass
        return registered

    def register_function(
        self,
        func: Callable,
        *,
        id: str | None = None,
        domain: str = "general",
        risk_level: str = "LOW",
        promote: bool = False,
        **kwargs: Any,
    ) -> Capability:
        cap = capability_from_function(func, id=id, domain=domain, risk_level=risk_level, **kwargs)
        return self.register(cap, promote=promote)

    def execute(
        self,
        capability_id: str,
        inputs: dict[str, Any] | None = None,
        execution_mode: ExecutionMode | str | None = None,
    ) -> ExecutionResponse:
        if self.is_remote:
            client = self._get_http_client()
            body = {"capability_id": capability_id, "inputs": inputs or {}}
            if execution_mode:
                body["execution_mode"] = str(execution_mode)
            resp = client.post("/v1/capabilities/execute", json=body)
            resp.raise_for_status()
            return ExecutionResponse.model_validate(resp.json())

        mode = ExecutionMode(str(execution_mode)) if execution_mode else ExecutionMode.CODE
        req = ExecutionRequest(
            capability_id=capability_id,
            inputs=inputs or {},
            execution_mode=mode,
        )
        return self.executor.execute(req)

    def execute_batch(
        self,
        requests: list[dict[str, Any] | ExecutionRequest],
    ) -> list[ExecutionResponse]:
        if self.is_remote:
            client = self._get_http_client()
            payload = []
            for r in requests:
                if isinstance(r, ExecutionRequest):
                    payload.append(r.model_dump(mode="json"))
                else:
                    payload.append(r)
            resp = client.post("/v1/capabilities/batch-execute", json={"requests": payload})
            resp.raise_for_status()
            return [ExecutionResponse.model_validate(r) for r in resp.json().get("responses", [])]

        responses = []
        for r in requests:
            if isinstance(r, ExecutionRequest):
                responses.append(self.executor.execute(r))
            else:
                responses.append(
                    self.execute(
                        r["capability_id"],
                        inputs=r.get("inputs"),
                        execution_mode=r.get("execution_mode"),
                    )
                )
        return responses

    def run_task(
        self,
        task_intent: str,
        inputs: dict[str, Any] | None = None,
        knowledge_spec: dict[str, Any] | None = None,
        agent_id: str | None = "default",
    ) -> AgentLifecycleTrace:
        return self.agent.handle_task(
            task_intent=task_intent,
            task_inputs=inputs or {},
            knowledge_spec=knowledge_spec,
            agent_id=agent_id,
        )

    def get(self, capability_id: str, version: str | None = None) -> Capability | None:
        if self.is_remote:
            client = self._get_http_client()
            url = f"/v1/capabilities/{capability_id}"
            if version:
                url += f"?version={version}"
            resp = client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return Capability.model_validate(resp.json())
        return self.registry.get(capability_id, version=version)

    def list_capabilities(
        self,
        *,
        domain: str | None = None,
        status: CapabilityStatus | None = None,
        namespace: str | None = None,
    ) -> list[Capability]:
        if self.is_remote:
            client = self._get_http_client()
            params: dict[str, Any] = {}
            if domain:
                params["domain"] = domain
            if status:
                params["status"] = status.value if hasattr(status, "value") else str(status)
            if namespace:
                params["namespace"] = namespace
            resp = client.get("/v1/capabilities", params=params)
            resp.raise_for_status()
            return [Capability.model_validate(c) for c in resp.json()]
        return self.registry.list_capabilities(domain=domain, status=status, namespace=namespace)

    def search(self, query: str, threshold: float = 0.2) -> list[tuple[Capability, float]]:
        if self.is_remote:
            client = self._get_http_client()
            resp = client.post("/v1/capabilities/search", json={"query": query, "threshold": threshold})
            resp.raise_for_status()
            return [(Capability.model_validate(c), 1.0) for c in resp.json()]
        from capforge.registry.search import CapabilityMatcher

        matcher = CapabilityMatcher(self.registry)
        return matcher.find_matches(query=query, threshold=threshold)

    def evaluate(self, cap_or_id: Capability | str) -> VerificationResult:
        if self.is_remote:
            cap_id = cap_or_id if isinstance(cap_or_id, str) else cap_or_id.id
            client = self._get_http_client()
            resp = client.post(f"/v1/capabilities/{cap_id}/evaluate")
            resp.raise_for_status()
            return VerificationResult.model_validate(resp.json())

        if isinstance(cap_or_id, str):
            cap = self.registry.get(cap_or_id)
            if not cap:
                raise ValueError(f"Capability '{cap_or_id}' not found in registry.")
        else:
            cap = cap_or_id
        return self.evaluator.evaluate(cap)

    def scan(self, capability_id: str, code: str | None = None) -> Any:
        if code is None:
            cap = self.get(capability_id)
            if not cap:
                raise ValueError(f"Capability '{capability_id}' not found.")
            code = cap.code_body
        return self.guardian.scan(capability_id, code)

    def register_batch(
        self,
        capabilities: list[Capability | Callable],
        *,
        promote: bool = False,
    ) -> list[Capability]:
        if self.is_remote:
            client = self._get_http_client()
            payload = []
            for c in capabilities:
                if callable(c) and hasattr(c, "capforge_capability"):
                    payload.append(c.capforge_capability.model_dump(mode="json"))
                elif isinstance(c, Capability):
                    payload.append(c.model_dump(mode="json"))
                elif callable(c):
                    payload.append(capability_from_function(c).model_dump(mode="json"))
            resp = client.post("/v1/capabilities/batch-register", json={"capabilities": payload, "promote": promote})
            resp.raise_for_status()
            return [Capability.model_validate(c) for c in resp.json().get("registered", [])]

        results = []
        for cap in capabilities:
            try:
                registered = self.register(cap, promote=promote)
                results.append(registered)
            except Exception as e:
                logger.error("Failed to register capability: %s", e)
        return results

    def evaluate_batch(self, capability_ids: list[str]) -> dict[str, VerificationResult]:
        if self.is_remote:
            client = self._get_http_client()
            resp = client.post("/v1/capabilities/batch-evaluate", json={"capability_ids": capability_ids})
            resp.raise_for_status()
            return {cid: VerificationResult.model_validate(res) for cid, res in resp.json().get("results", {}).items()}

        results = {}
        for cap_id in capability_ids:
            try:
                results[cap_id] = self.evaluate(cap_id)
            except Exception as e:
                logger.error("Failed to evaluate '%s': %s", cap_id, e)
        return results

    def as_tool(self, capability_id: str) -> dict[str, Any]:
        """Export a capability as an OpenAI / standard LLM function tool schema."""
        cap = self.get(capability_id)
        if not cap:
            raise ValueError(f"Capability '{capability_id}' not found.")
        return cap.to_tool()

    def subscribe_webhook(
        self,
        url: str,
        events: list[str] | None = None,
        secret: str | None = None,
        description: str = "",
    ) -> WebhookSubscription:
        if self.is_remote:
            client = self._get_http_client()
            resp = client.post(
                "/v1/webhooks",
                json={"url": url, "events": events or [], "secret": secret, "description": description},
            )
            resp.raise_for_status()
            return WebhookSubscription.model_validate(resp.json())

        sub = WebhookSubscription(url=url, events=events or [], secret=secret, description=description)
        return self.webhooks.register(sub)

    def unsubscribe_webhook(self, webhook_id: str) -> bool:
        if self.is_remote:
            client = self._get_http_client()
            resp = client.delete(f"/v1/webhooks/{webhook_id}")
            return resp.status_code == 200
        return self.webhooks.unregister(webhook_id)

    def list_webhooks(self, active_only: bool = True) -> list[WebhookSubscription]:
        if self.is_remote:
            client = self._get_http_client()
            resp = client.get(f"/v1/webhooks?active_only={str(active_only).lower()}")
            resp.raise_for_status()
            return [WebhookSubscription.model_validate(w) for w in resp.json()]
        return self.webhooks.list_subscriptions(active_only=active_only)

    def dispatch_event(self, event_type: str, payload: dict[str, Any]) -> list[WebhookDelivery]:
        if self.is_remote:
            client = self._get_http_client()
            resp = client.post("/v1/webhooks/test", json={"event_type": event_type, "payload": payload})
            resp.raise_for_status()
            return [WebhookDelivery.model_validate(d) for d in resp.json().get("deliveries", [])]
        return self.webhooks.dispatch(event_type, payload)

    def get_delivery_log(self, webhook_id: str | None = None, limit: int = 50) -> list[WebhookDelivery]:
        if self.is_remote:
            client = self._get_http_client()
            params: dict[str, Any] = {"limit": limit}
            if webhook_id:
                params["webhook_id"] = webhook_id
            resp = client.get("/v1/webhooks/deliveries", params=params)
            resp.raise_for_status()
            return [WebhookDelivery.model_validate(d) for d in resp.json()]
        return self.webhooks.get_delivery_log(webhook_id=webhook_id, limit=limit)

    def health_check(self) -> dict[str, Any]:
        if self.is_remote:
            client = self._get_http_client()
            resp = client.get("/health")
            resp.raise_for_status()
            return resp.json()

        status: dict[str, Any] = {"version": "1.1.0", "subsystems": {}}
        try:
            count = len(self.registry.list_capabilities())
            status["subsystems"]["registry"] = {"status": "ok", "capability_count": count}
        except Exception as e:
            status["subsystems"]["registry"] = {"status": "error", "error": str(e)}
        try:
            self.evaluator
            status["subsystems"]["evaluator"] = {"status": "ok"}
        except Exception as e:
            status["subsystems"]["evaluator"] = {"status": "error", "error": str(e)}
        try:
            self.guardian
            status["subsystems"]["security"] = {"status": "ok"}
        except Exception as e:
            status["subsystems"]["security"] = {"status": "error", "error": str(e)}
        try:
            count = len(self.webhooks.list_subscriptions())
            status["subsystems"]["webhooks"] = {"status": "ok", "active_subscriptions": count}
        except Exception as e:
            status["subsystems"]["webhooks"] = {"status": "error", "error": str(e)}
        return status

    def info(self) -> dict[str, Any]:
        caps = self.list_capabilities()
        status_counts: dict[str, int] = {}
        for cap in caps:
            key = cap.status.value
            status_counts[key] = status_counts.get(key, 0) + 1
        return {
            "version": "1.1.0",
            "mode": "remote" if self.is_remote else "local",
            "total_capabilities": len(caps),
            "status_breakdown": status_counts,
        }


class SecurityError(Exception):
    """Raised when a capability fails security scanning."""
