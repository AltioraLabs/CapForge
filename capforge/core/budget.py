"""CapForge Evolution Budget Manager & Cost Controller.

Enforces computational and financial quotas on continuous capability evolution
(discussion.mdx §22-§26; SPECIFICATION §22, §23, §26 #14-#16).

Prevents runaway API costs, bounds sandbox compute, and answers the central invariant:
"Is the expected benefit of evolving this capability worth the cost of doing so?"
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("capforge.budget")


class BudgetConfig(BaseModel):
    """Configuration limits for autonomous evolution compute and API expenditure."""

    max_llm_calls_per_hour: int = Field(default=120, description="Max LLM diagnosis & synthesis calls per hour")
    max_llm_calls_per_day: int = Field(default=1000, description="Max LLM calls per 24h window")
    max_cost_per_day_usd: float = Field(default=25.00, description="Daily USD expenditure ceiling for evolution")
    max_sandbox_runs_per_day: int = Field(default=200, description="Daily container sandbox execution ceiling")
    min_expected_gain_pct: float = Field(
        default=5.0,
        description="Minimum expected performance or reliability gain percentage to justify evolution",
    )


class EvolutionBudgetManager:
    """Tracks and enforces resource quotas for the learning and evolution plane."""

    def __init__(self, config: BudgetConfig | None = None) -> None:
        self.config = config or BudgetConfig()

        self._hourly_calls: int = 0
        self._daily_calls: int = 0
        self._daily_cost_usd: float = 0.0
        self._daily_sandbox_runs: int = 0

        self._current_hour: int = datetime.now(UTC).hour
        self._current_day: int = datetime.now(UTC).day
        self._last_reset: datetime = datetime.now(UTC)

    def _auto_rotate(self) -> None:
        """Rotates hourly and daily quota counters if the clock has advanced."""
        now = datetime.now(UTC)
        if now.hour != self._current_hour or (now - self._last_reset).total_seconds() >= 3600:
            self._hourly_calls = 0
            self._current_hour = now.hour

        if now.day != self._current_day or (now - self._last_reset).total_seconds() >= 86400:
            self._daily_calls = 0
            self._daily_cost_usd = 0.0
            self._daily_sandbox_runs = 0
            self._current_day = now.day
            self._last_reset = now

    def can_evolve(
        self,
        capability_id: str,
        priority: str = "MEDIUM",
        estimated_cost_usd: float = 0.05,
        expected_gain_pct: float = 10.0,
    ) -> tuple[bool, str]:
        """Evaluates whether an evolution job is permitted under current resource and financial quotas."""
        self._auto_rotate()

        priority_upper = priority.upper()

        # Rule 1: Expected gain threshold
        if expected_gain_pct < self.config.min_expected_gain_pct:
            msg = (
                f"Evolution rejected for '{capability_id}': Expected gain {expected_gain_pct:.1f}% "
                f"is below minimum threshold {self.config.min_expected_gain_pct:.1f}%."
            )
            logger.warning(msg)
            return False, msg

        # Rule 2: Hourly LLM call limit
        if self._hourly_calls >= self.config.max_llm_calls_per_hour:
            msg = f"Evolution throttled for '{capability_id}': Hourly LLM call limit reached ({self.config.max_llm_calls_per_hour}/hr)."
            logger.warning(msg)
            return False, msg

        # Rule 3: Daily LLM call limit
        if self._daily_calls >= self.config.max_llm_calls_per_day:
            msg = f"Evolution paused for '{capability_id}': Daily LLM call quota reached ({self.config.max_llm_calls_per_day}/day)."
            logger.warning(msg)
            return False, msg

        # Rule 4: Daily cost cap
        if (self._daily_cost_usd + estimated_cost_usd) > self.config.max_cost_per_day_usd:
            msg = (
                f"Evolution blocked for '{capability_id}': Daily budget ceiling exceeded "
                f"(${self._daily_cost_usd:.2f} + ${estimated_cost_usd:.2f} > ${self.config.max_cost_per_day_usd:.2f})."
            )
            logger.warning(msg)
            return False, msg

        # Rule 5: Sandbox execution ceiling
        if self._daily_sandbox_runs >= self.config.max_sandbox_runs_per_day:
            msg = f"Evolution blocked for '{capability_id}': Daily sandbox execution limit reached ({self.config.max_sandbox_runs_per_day}/day)."
            logger.warning(msg)
            return False, msg

        # Rule 6: Low-priority preservation (reserve last 20% of budget for HIGH/MEDIUM priority)
        budget_remaining_pct = max(0.0, 1.0 - (self._daily_cost_usd / max(self.config.max_cost_per_day_usd, 0.01)))
        if priority_upper == "LOW" and budget_remaining_pct < 0.20:
            msg = (
                f"Low-priority evolution deferred for '{capability_id}': "
                f"Only {budget_remaining_pct * 100:.1f}% daily budget remains (reserved for critical capabilities)."
            )
            logger.info(msg)
            return False, msg

        return True, "Evolution approved within budget and compute quotas."

    def record_llm_call(self, tokens: int = 0, cost_usd: float = 0.0, model: str = "default") -> None:
        """Records an LLM API invocation against active hourly and daily budgets."""
        self._auto_rotate()
        self._hourly_calls += 1
        self._daily_calls += 1
        self._daily_cost_usd += max(0.0, cost_usd)
        logger.debug(
            "Recorded LLM call: model=%s, tokens=%d, cost=$%.4f (daily_total=$%.2f)",
            model,
            tokens,
            cost_usd,
            self._daily_cost_usd,
        )

    def record_sandbox_run(self) -> None:
        """Records a sandboxed container execution."""
        self._auto_rotate()
        self._daily_sandbox_runs += 1

    def get_budget_status(self) -> dict[str, Any]:
        """Returns the current quota consumption status."""
        self._auto_rotate()
        return {
            "hourly_calls": self._hourly_calls,
            "max_hourly_calls": self.config.max_llm_calls_per_hour,
            "daily_calls": self._daily_calls,
            "max_daily_calls": self.config.max_llm_calls_per_day,
            "daily_cost_usd": round(self._daily_cost_usd, 4),
            "max_cost_usd": self.config.max_cost_per_day_usd,
            "cost_utilization_pct": round((self._daily_cost_usd / max(self.config.max_cost_per_day_usd, 0.01)) * 100, 2),
            "daily_sandbox_runs": self._daily_sandbox_runs,
            "max_sandbox_runs": self.config.max_sandbox_runs_per_day,
        }

    def reset_quotas(self) -> None:
        """Explicitly resets all usage counters (for administrative testing)."""
        self._hourly_calls = 0
        self._daily_calls = 0
        self._daily_cost_usd = 0.0
        self._daily_sandbox_runs = 0
        self._last_reset = datetime.now(UTC)


# Global default instance
budget_manager = EvolutionBudgetManager()
