"""CapForge REST API Application.

Provides HTTP endpoints for task gap analysis, capability registration,
version inspection, execution dispatch, lifecycle control, events,
governance, learning jobs, manifest import/export, and capability graph queries.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from capforge.acquisition.engine import AcquisitionEngine
from capforge.acquisition.jobs import LearningJob, LearningJobManager
from capforge.core.config import settings, setup_logging
from capforge.core.events import EventGateway, ExperienceFilter
from capforge.core.governance import (
    CapabilityFirewall,
    HumanReviewTicket,
    RiskAssessment,
    RiskEngine,
)
from capforge.core.manifest import (
    capability_to_yaml,
    manifest_yaml_to_capability,
)
from capforge.core.models import (
    AgentEvent,
    Capability,
    CapabilityGap,
    CapabilityStatus,
    ExecutionRequest,
    ExecutionResponse,
    VerificationResult,
)
from capforge.core.telemetry import trace_manager
from capforge.discovery.capability_graph import CapabilityGraph, ImpactReport
from capforge.discovery.gap_detector import CapabilityGapDetector
from capforge.events.broker import StreamMessage
from capforge.mcp.server import CapForgeMCPServer
from capforge.registry.search import CapabilityMatcher
from capforge.registry.store import CapabilityRegistry
from capforge.registry.vector_store import SemanticVectorIndex
from capforge.runtime.agent_adapter import CapForgeAgent
from capforge.runtime.composition import CompositionEngine
from capforge.runtime.durable_workflow import (
    DurableWorkflowEngine,
    WorkflowDefinition,
    WorkflowExecutionState,
)
from capforge.runtime.executor import CapabilityExecutor
from capforge.runtime.pipeline import (
    CapabilityPipeline,
    CapabilityPipelineRunner,
    PipelineExecutionResponse,
)
from capforge.server.auth import (
    APIKeyRecord,
    UserRole,
    auth_manager,
    require_roles,
)
from capforge.verification.evaluator import CapabilityEvaluator
from capforge.verification.test_generator import TestGenerator
from capforge.versioning.manager import VersionManager

# Configure logging
setup_logging()
logger = logging.getLogger("capforge.api")

# Rate limiter (uses client IP; upgrade to auth key ID for per-tenant limits)
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_default])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: startup and shutdown hooks."""
    logger.info(
        "CapForge API starting | version=1.1.0 | dev_mode=%s | llm=%s | redis=%s",
        settings.dev_mode,
        settings.llm_provider if settings.llm_configured else "template-fallback",
        "configured" if settings.redis_configured else "in-memory-fallback",
    )
    yield
    logger.info("CapForge API shutting down.")


app = FastAPI(
    title="CapForge API",
    description="Autonomous Capability Acquisition, Verification, and Evolution Runtime for AI Agents",
    version="1.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared platform singletons
registry = CapabilityRegistry()
risk_engine = RiskEngine()
firewall = CapabilityFirewall(risk_engine)
matcher = CapabilityMatcher(registry)
vector_index = SemanticVectorIndex(registry)
gap_detector = CapabilityGapDetector(registry)
acquisition_engine = AcquisitionEngine()
test_generator = TestGenerator()
evaluator = CapabilityEvaluator()
version_manager = VersionManager(registry, risk_engine)
executor = CapabilityExecutor(registry, firewall=firewall)
composition_engine = CompositionEngine(registry)
pipeline_runner = CapabilityPipelineRunner(executor)
event_gateway = EventGateway()
durable_workflow_engine = DurableWorkflowEngine(executor=executor, event_gateway=event_gateway)
experience_filter = ExperienceFilter()
capability_graph = CapabilityGraph(registry)
sf_agent = CapForgeAgent(registry)
job_manager = LearningJobManager(sf_agent)
mcp_server = CapForgeMCPServer(registry=registry, executor=executor)


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------


class TaskAnalyzeRequest(BaseModel):
    task_intent: str


class CapabilitySearchRequest(BaseModel):
    query: str
    top_k: int = 5
    domain: str | None = None


class RollbackRequest(BaseModel):
    target_version: str


class CreateLearningJobRequest(BaseModel):
    task_intent: str
    task_inputs: dict[str, Any] = Field(default_factory=dict)
    knowledge_spec: dict[str, Any] | None = None


class PromoteRequest(BaseModel):
    skip_regression: bool = False
    skip_risk_check: bool = False


# ---------------------------------------------------------------------------
# Health & Dashboard UI
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": "capforge",
        "version": "1.1.0",
        "dev_mode": str(settings.dev_mode),
    }


@app.get("/health/ready", tags=["Health"])
def readiness_check() -> dict[str, str]:
    """Kubernetes readiness probe — checks DB is accessible."""
    try:
        registry.list_capabilities(limit=1)
        return {"status": "ready"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Not ready: {e}")


@app.get("/", response_class=HTMLResponse, tags=["Dashboard"], include_in_schema=False)
@app.get("/dashboard", response_class=HTMLResponse, tags=["Dashboard"])
def get_dashboard_ui() -> HTMLResponse:
    """Serve the CapForge Control Center Web Dashboard."""
    dashboard_path = Path(__file__).parent / "dashboard.html"
    if dashboard_path.exists():
        return HTMLResponse(content=dashboard_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>CapForge Control Center</h1><p>Dashboard HTML not found.</p>")


@app.get("/v1/dashboard/stats", tags=["Dashboard"])
def get_dashboard_stats() -> dict[str, Any]:
    """Summary metrics for the Section 46 Control Center Dashboard."""
    caps = registry.list_capabilities()
    active_caps = [c for c in caps if c.status == CapabilityStatus.ACTIVE]
    jobs = job_manager.list_jobs()
    active_jobs = [j for j in jobs if j.status in ("QUEUED", "RUNNING")]

    return {
        "capabilities_count": len(caps),
        "active_capabilities_count": len(active_caps),
        "agents_connected": 1,
        "active_learning_jobs": len(active_jobs),
        "firewall_pass_rate": 100,
        "tools_count": sum(len(c.tools_required) for c in caps),
    }


# ---------------------------------------------------------------------------
# v1 — Discovery & Search
# ---------------------------------------------------------------------------


@app.post("/v1/capabilities/analyze", response_model=CapabilityGap, tags=["Discovery"])
def analyze_task_gap(req: TaskAnalyzeRequest):
    """Analyze a task and determine if a capability gap exists."""
    return gap_detector.evaluate_task(req.task_intent)


@app.post("/v1/capabilities/search", response_model=list[Capability], tags=["Discovery"])
def search_capabilities(req: CapabilitySearchRequest):
    """Search registered capabilities using tag and description overlap matching."""
    matches = matcher.match(req.query, top_k=req.top_k)
    return [match.capability for match in matches]


# ---------------------------------------------------------------------------
# v1 — Registry & Manifests
# ---------------------------------------------------------------------------


@app.get("/v1/capabilities", response_model=list[Capability], tags=["Registry"])
def list_capabilities(
    domain: str | None = Query(None),
    cap_status: CapabilityStatus | None = Query(None, alias="status"),
    namespace: str | None = Query(None),
    limit: int | None = Query(None, ge=1, le=500, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
):
    """List registered capabilities with optional filtering and pagination."""
    return registry.list_capabilities(domain=domain, status=cap_status, namespace=namespace, limit=limit, offset=offset)


@app.get("/v1/capabilities/{capability_id}", response_model=Capability, tags=["Registry"])
def get_capability(capability_id: str, version: str | None = None):
    """Get a specific capability by ID and optional version."""
    cap = registry.get(capability_id, version=version)
    if not cap:
        raise HTTPException(status_code=404, detail=f"Capability '{capability_id}' not found.")
    return cap


@app.get("/v1/capabilities/{capability_id}/versions", response_model=list[Capability], tags=["Registry"])
def list_capability_versions(capability_id: str):
    """List all version records for a capability."""
    versions = registry.list_versions(capability_id)
    if not versions:
        raise HTTPException(status_code=404, detail=f"No versions found for '{capability_id}'.")
    return versions


@app.post("/v1/capabilities/register", response_model=Capability, tags=["Registry"])
def register_capability(capability: Capability, promote: bool = False):
    """Register a new capability in the registry."""
    # Assess risk and open audit review ticket if high risk or AST anomalies detected
    risk_assessment = risk_engine.assess(capability)
    capability.risk_level = risk_assessment.risk_level

    if promote:
        candidate = capability.model_copy()
        candidate.verification_tests = test_generator.enrich_tests(candidate)
        version_manager.promote_to_active(candidate)
        result = candidate
    else:
        result = registry.register(capability)

    # Keep vector index fresh — auto-index newly registered capability
    vector_index.on_capability_registered(result)
    return result


@app.post("/v1/capabilities/manifest/import", response_model=Capability, tags=["Manifest"])
def import_capability_manifest(manifest_yaml: str = Body(..., media_type="text/plain")):
    """Import and validate a capability definition from YAML manifest (discussion.mdx §12)."""
    try:
        cap = manifest_yaml_to_capability(manifest_yaml)
        return registry.register(cap)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid manifest: {e}")


@app.get("/v1/capabilities/{capability_id}/manifest", response_class=PlainTextResponse, tags=["Manifest"])
def export_capability_manifest(capability_id: str, version: str | None = None) -> PlainTextResponse:
    """Export a capability as a canonical YAML manifest."""
    cap = registry.get(capability_id, version=version)
    if not cap:
        raise HTTPException(status_code=404, detail=f"Capability '{capability_id}' not found.")
    yaml_str = capability_to_yaml(cap)
    return PlainTextResponse(content=yaml_str, media_type="application/x-yaml")


# ---------------------------------------------------------------------------
# v1 — Learning Jobs (discussion.mdx §19, §38)
# ---------------------------------------------------------------------------


@app.post("/v1/learning/jobs", response_model=LearningJob, tags=["Learning"])
def create_learning_job(req: CreateLearningJobRequest):
    """Trigger autonomous acquisition workflow for a missing capability."""
    job = job_manager.create_job(
        task_intent=req.task_intent,
        task_inputs=req.task_inputs,
        knowledge_spec=req.knowledge_spec,
    )
    # Execute job synchronously to return completed result
    return job_manager.execute_job_sync(job.job_id)


@app.get("/v1/learning/jobs", response_model=list[LearningJob], tags=["Learning"])
def list_learning_jobs(status: str | None = Query(None)):
    """List all tracked capability learning jobs."""
    return job_manager.list_jobs(status=status)


@app.get("/v1/learning/jobs/{job_id}", response_model=LearningJob, tags=["Learning"])
def get_learning_job(job_id: str):
    """Get status, progress, and results of a learning job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Learning job '{job_id}' not found.")
    return job


# ---------------------------------------------------------------------------
# v1 — Evaluation & Verification (§24)
# ---------------------------------------------------------------------------


@app.post("/v1/capabilities/{capability_id}/evaluate", response_model=VerificationResult, tags=["Verification"])
@app.post(
    "/v1/skills/{capability_id}/evaluate",
    response_model=VerificationResult,
    tags=["Verification"],
    include_in_schema=False,
)
def evaluate_capability(capability_id: str, version: str | None = None):
    """Run four-level verification tests on a capability."""
    cap = registry.get(capability_id, version=version)
    if not cap:
        raise HTTPException(status_code=404, detail=f"Capability '{capability_id}' not found.")
    return evaluator.evaluate(cap)


# ---------------------------------------------------------------------------
# v1 — Versioning & Promotion
# ---------------------------------------------------------------------------


@app.post("/v1/capabilities/{capability_id}/promote", response_model=Capability, tags=["Versioning"])
@app.post("/v1/skills/{capability_id}/promote", response_model=Capability, tags=["Versioning"], include_in_schema=False)
def promote_capability(capability_id: str, req: PromoteRequest = Body(default=PromoteRequest())):
    """Promote a candidate capability through verification and risk policy gates."""
    cap = registry.get(capability_id)
    if not cap:
        raise HTTPException(status_code=404, detail=f"Capability '{capability_id}' not found.")
    try:
        verif, risk = version_manager.promote_to_active(
            cap,
            skip_regression=req.skip_regression,
            skip_risk_check=req.skip_risk_check,
        )
        return registry.get(capability_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/v1/capabilities/{capability_id}/rollback", response_model=Capability, tags=["Versioning"])
@app.post(
    "/v1/skills/{capability_id}/rollback", response_model=Capability, tags=["Versioning"], include_in_schema=False
)
def rollback_capability(capability_id: str, req: RollbackRequest):
    """Roll back a capability to a previous version."""
    try:
        return version_manager.rollback(capability_id, req.target_version)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get(
    "/v1/skills/{capability_id}/versions", response_model=list[Capability], tags=["Versioning"], include_in_schema=False
)
def legacy_skill_versions(capability_id: str):
    return list_capability_versions(capability_id)


# ---------------------------------------------------------------------------
# v1 — Execution
# ---------------------------------------------------------------------------


@app.post("/v1/capabilities/execute", response_model=ExecutionResponse, tags=["Execution"])
def execute_capability(req: ExecutionRequest):
    """Execute a capability inside the secure sandbox with firewall enforcement."""
    try:
        return executor.execute(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# v1 — Governance & Firewall (§26, §27)
# ---------------------------------------------------------------------------


@app.post("/v1/capabilities/{capability_id}/assess-risk", response_model=RiskAssessment, tags=["Governance"])
def assess_capability_risk(capability_id: str, version: str | None = None):
    """Assess the risk level of a capability."""
    cap = registry.get(capability_id, version=version)
    if not cap:
        raise HTTPException(status_code=404, detail=f"Capability '{capability_id}' not found.")
    return risk_engine.assess(cap)


# ---------------------------------------------------------------------------
# v1 — Events (§9, §16)
# ---------------------------------------------------------------------------


@app.post("/v1/events", tags=["Events"])
def receive_event(event: AgentEvent):
    """Receive a normalized agent event via the Event Gateway."""
    event_gateway.emit(event)
    should_learn = experience_filter.should_learn(event)
    return {
        "received": True,
        "event_id": event.event_id,
        "should_learn": should_learn,
    }


@app.get("/v1/events/recent", tags=["Events"])
def get_recent_events(limit: int = Query(50, ge=1, le=500)):
    """Get recent events from the Event Gateway log."""
    return event_gateway.get_recent_events(limit=limit)


# ---------------------------------------------------------------------------
# v1 — Capability Graph (§32)
# ---------------------------------------------------------------------------


@app.get("/v1/capability-graph/{capability_id}", tags=["Graph"])
@app.get("/v1/capability-graph/{capability_id}/impact", response_model=ImpactReport, tags=["Graph"])
def get_impact_analysis(capability_id: str):
    """Get impact analysis and transitive dependents for a capability change."""
    capability_graph.build_from_registry()
    return capability_graph.impact_analysis(capability_id)


@app.get("/v1/capability-graph/{capability_id}/dependencies", tags=["Graph"])
def get_dependencies(capability_id: str):
    """Get dependencies of a capability."""
    capability_graph.build_from_registry()
    return {
        "capability_id": capability_id,
        "dependencies": capability_graph.get_dependencies(capability_id),
    }


# ---------------------------------------------------------------------------
# v1 — Composition
# ---------------------------------------------------------------------------


@app.get("/v1/primitives", tags=["Composition"])
def list_primitives():
    """List available reusable primitives."""
    return composition_engine.STANDARD_PRIMITIVES


# ---------------------------------------------------------------------------
# v1 — Model Context Protocol (MCP)
# ---------------------------------------------------------------------------


@app.get("/mcp/tools", tags=["MCP"])
def get_mcp_tools():
    """List standard MCP tool definitions."""
    return {"tools": mcp_server.get_tool_definitions()}


@app.post("/mcp/rpc", tags=["MCP"])
def handle_mcp_rpc(payload: dict[str, Any] = Body(...)):
    """Handle standard JSON-RPC 2.0 MCP messages."""
    return mcp_server.handle_message(payload)


# ---------------------------------------------------------------------------
# v1 — Capability Pipelines
# ---------------------------------------------------------------------------


@app.post("/v1/pipelines/run", response_model=PipelineExecutionResponse, tags=["Pipelines"])
def run_capability_pipeline(
    pipeline: CapabilityPipeline = Body(...),
    initial_inputs: dict[str, Any] = Body(default_factory=dict),
):
    """Execute a multi-step capability composition pipeline."""
    return pipeline_runner.run_pipeline(pipeline, initial_inputs)


# ---------------------------------------------------------------------------
# v1 — OpenTelemetry Spans
# ---------------------------------------------------------------------------


@app.get("/v1/telemetry/spans", tags=["Telemetry"])
def list_telemetry_spans(
    trace_id: str | None = Query(None),
    name: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """Retrieve recorded distributed tracing spans."""
    return trace_manager.list_spans(trace_id=trace_id, name=name, limit=limit)


# ---------------------------------------------------------------------------
# v1 — Governance Review Tickets Lifecycle
# ---------------------------------------------------------------------------


class TicketActionRequest(BaseModel):
    reviewer: str = "security_lead"
    notes: str = ""


@app.get("/v1/governance/tickets", response_model=list[HumanReviewTicket], tags=["Governance"])
def list_governance_tickets(status: str | None = Query(None)):
    """List audit tickets flagged for human review due to risk escalation or AST anomalies."""
    return risk_engine.list_tickets(status=status)


@app.post("/v1/governance/tickets/{ticket_id}/approve", response_model=HumanReviewTicket, tags=["Governance"])
def approve_governance_ticket(ticket_id: str, req: TicketActionRequest = Body(...)):
    """Approve a flagged capability review ticket and promote/activate the capability."""
    try:
        ticket = risk_engine.approve_ticket(ticket_id, reviewer=req.reviewer, notes=req.notes)
        cap = registry.get(ticket.capability_id, version=ticket.version)
        if cap:
            cap.status = CapabilityStatus.ACTIVE
            registry.register(cap)
        return ticket
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/v1/governance/tickets/{ticket_id}/reject", response_model=HumanReviewTicket, tags=["Governance"])
def reject_governance_ticket(ticket_id: str, req: TicketActionRequest = Body(...)):
    """Reject a flagged capability review ticket and quarantine the capability."""
    try:
        ticket = risk_engine.reject_ticket(ticket_id, reviewer=req.reviewer, notes=req.notes)
        cap = registry.get(ticket.capability_id, version=ticket.version)
        if cap:
            cap.status = CapabilityStatus.QUARANTINED
            registry.register(cap)
        return ticket
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# v1 — Distributed Event Stream & Durable Workflows
# ---------------------------------------------------------------------------


class WorkflowRunRequest(BaseModel):
    workflow: WorkflowDefinition
    inputs: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None


@app.get("/v1/events/stream", response_model=list[StreamMessage], tags=["Events"])
def get_event_stream(
    topic_pattern: str = Query("*"),
    since_timestamp: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """Query streamed agent events from the distributed event broker."""
    return event_gateway.broker.replay(
        topic_pattern=topic_pattern,
        since_timestamp=since_timestamp,
        limit=limit,
    )


@app.post("/v1/workflows/execute", response_model=WorkflowExecutionState, tags=["Workflows"])
def execute_workflow(req: WorkflowRunRequest):
    """Execute a durable multi-step workflow with state checkpointing and automatic backoff."""
    return durable_workflow_engine.start_workflow(
        workflow=req.workflow,
        inputs=req.inputs,
        run_id=req.run_id,
    )


@app.get("/v1/workflows", response_model=list[WorkflowExecutionState], tags=["Workflows"])
def list_workflows(limit: int = Query(50, ge=1, le=100)):
    """List recent durable workflow runs and their status."""
    return durable_workflow_engine.list_workflow_runs(limit=limit)


@app.get("/v1/workflows/{run_id}", response_model=WorkflowExecutionState, tags=["Workflows"])
def get_workflow_state(run_id: str):
    """Inspect durable checkpoints and execution state of a workflow run."""
    state = durable_workflow_engine.get_workflow_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Workflow run '{run_id}' not found.")
    return state


@app.post("/v1/workflows/{run_id}/resume", response_model=WorkflowExecutionState, tags=["Workflows"])
def resume_workflow(run_id: str):
    """Resume a paused or failed durable workflow from its last valid checkpoint."""
    try:
        return durable_workflow_engine.resume_workflow(run_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# v1 — Hybrid Vector Retrieval & Enterprise Auth Mesh
# ---------------------------------------------------------------------------


class HybridSearchRequest(BaseModel):
    query: str
    alpha: float = 0.5
    top_k: int = 5
    status: CapabilityStatus | None = None


class HybridSearchResult(BaseModel):
    capability: Capability
    score: float


class CreateKeyRequest(BaseModel):
    name: str
    role: UserRole = UserRole.AGENT_RUNNER
    tenant_namespace: str = "default"


class CreateKeyResponse(BaseModel):
    api_key: str
    record: APIKeyRecord


@app.post("/v1/capabilities/hybrid-search", response_model=list[HybridSearchResult], tags=["Search"])
def hybrid_search_capabilities(req: HybridSearchRequest):
    """Hybrid lexical + dense vector semantic retrieval for capabilities."""
    results = vector_index.hybrid_search(
        query=req.query,
        alpha=req.alpha,
        top_k=req.top_k,
        status=req.status,
    )
    return [{"capability": cap, "score": score} for cap, score in results]


@app.post("/v1/auth/keys", response_model=CreateKeyResponse, tags=["Security & Auth"])
def create_api_key(
    req: CreateKeyRequest,
    current_user: APIKeyRecord = Depends(require_roles(UserRole.ADMIN, UserRole.OPERATOR)),
):
    """Provision a new cryptographically hashed API key with scoped role and tenant boundaries."""
    raw_token, rec = auth_manager.create_api_key(
        name=req.name,
        role=req.role,
        tenant_namespace=req.tenant_namespace,
    )
    return {"api_key": raw_token, "record": rec}


@app.get("/v1/auth/keys", response_model=list[APIKeyRecord], tags=["Security & Auth"])
def list_api_keys(
    current_user: APIKeyRecord = Depends(require_roles(UserRole.ADMIN, UserRole.OPERATOR)),
):
    """List provisioned API keys and their status."""
    return auth_manager.list_keys()


@app.post("/v1/auth/keys/{key_id}/revoke", tags=["Security & Auth"])
def revoke_api_key(
    key_id: str,
    current_user: APIKeyRecord = Depends(require_roles(UserRole.ADMIN)),
):
    """Revoke an active API key."""
    success = auth_manager.revoke_key(key_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"API key '{key_id}' not found.")
    return {"revoked": True, "key_id": key_id}


# ---------------------------------------------------------------------------
# Backward Compatibility Routes
# ---------------------------------------------------------------------------


@app.post("/api/tasks/analyze", response_model=CapabilityGap, tags=["Legacy"], include_in_schema=False)
def legacy_analyze_task_gap(req: TaskAnalyzeRequest):
    return gap_detector.evaluate_task(req.task_intent)


@app.get("/api/capabilities", response_model=list[Capability], tags=["Legacy"], include_in_schema=False)
def legacy_list_capabilities(
    domain: str | None = Query(None),
    cap_status: CapabilityStatus | None = Query(None, alias="status"),
):
    return registry.list_capabilities(domain=domain, status=cap_status)
