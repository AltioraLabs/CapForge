"""SkillForge REST API Application.

Provides HTTP endpoints for task gap analysis, capability registration,
version inspection, execution dispatch, and lifecycle control.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from skillforge.core.models import (
    Capability,
    CapabilityGap,
    CapabilityStatus,
    ExecutionRequest,
    ExecutionResponse,
    VerificationResult
)
from skillforge.registry.store import CapabilityRegistry
from skillforge.discovery.gap_detector import CapabilityGapDetector
from skillforge.acquisition.engine import AcquisitionEngine
from skillforge.verification.evaluator import CapabilityEvaluator
from skillforge.verification.test_generator import TestGenerator
from skillforge.versioning.manager import VersionManager
from skillforge.runtime.executor import CapabilityExecutor
from skillforge.runtime.composition import CompositionEngine


app = FastAPI(
    title="SkillForge API",
    description="Autonomous Capability Acquisition, Verification, and Evolution Runtime for AI Agents",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared instances
registry = CapabilityRegistry()
gap_detector = CapabilityGapDetector(registry)
acquisition_engine = AcquisitionEngine()
test_generator = TestGenerator()
evaluator = CapabilityEvaluator()
version_manager = VersionManager(registry)
executor = CapabilityExecutor(registry)
composition_engine = CompositionEngine(registry)


class TaskAnalyzeRequest(BaseModel):
    task_intent: str


class RollbackRequest(BaseModel):
    target_version: str


@app.get("/health", tags=["Health"])
def health_check() -> Dict[str, str]:
    return {"status": "healthy", "service": "skillforge", "version": "0.1.0"}


@app.post("/api/tasks/analyze", response_model=CapabilityGap, tags=["Discovery"])
def analyze_task_gap(req: TaskAnalyzeRequest):
    """Analyze a task and determine if a capability gap exists."""
    return gap_detector.evaluate_task(req.task_intent)


@app.get("/api/capabilities", response_model=List[Capability], tags=["Registry"])
def list_capabilities(
    domain: Optional[str] = Query(None),
    status: Optional[CapabilityStatus] = Query(None)
):
    """List registered capabilities."""
    return registry.list_capabilities(domain=domain, status=status)


@app.get("/api/capabilities/{capability_id}", response_model=Capability, tags=["Registry"])
def get_capability(capability_id: str, version: Optional[str] = None):
    """Get a specific capability by ID and optional version."""
    cap = registry.get(capability_id, version=version)
    if not cap:
        raise HTTPException(status_code=404, detail=f"Capability '{capability_id}' not found.")
    return cap


@app.get("/api/capabilities/{capability_id}/versions", response_model=List[Capability], tags=["Registry"])
def list_capability_versions(capability_id: str):
    """List all version records for a capability."""
    versions = registry.list_versions(capability_id)
    if not versions:
        raise HTTPException(status_code=404, detail=f"No versions found for '{capability_id}'.")
    return versions


@app.post("/api/capabilities/register", response_model=Capability, tags=["Registry"])
def register_capability(capability: Capability, promote: bool = False):
    """Register a new capability in the registry."""
    if promote:
        candidate = capability.model_copy()
        candidate.verification_tests = test_generator.enrich_tests(candidate)
        version_manager.promote_to_active(candidate)
        return candidate
    else:
        return registry.register(capability)


@app.post("/api/capabilities/{capability_id}/rollback", response_model=Capability, tags=["Versioning"])
def rollback_capability(capability_id: str, req: RollbackRequest):
    """Roll back a capability to a previous version."""
    try:
        return version_manager.rollback(capability_id, req.target_version)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/capabilities/execute", response_model=ExecutionResponse, tags=["Execution"])
def execute_capability(req: ExecutionRequest):
    """Execute a capability inside the secure sandbox."""
    try:
        return executor.execute(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/primitives", tags=["Composition"])
def list_primitives():
    """List available reusable primitives."""
    return composition_engine.STANDARD_PRIMITIVES
