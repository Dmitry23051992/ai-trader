from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Context:
    """Shared context passed through the agent pipeline.

    Each agent reads from and writes to its corresponding namespace.
    """

    # Agent namespaces — populated by the respective agent
    market: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    strategy: dict[str, Any] = field(default_factory=dict)
    backtest: dict[str, Any] = field(default_factory=dict)
    learning: dict[str, Any] = field(default_factory=dict)

    # Pipeline metadata
    candidate_name: str = ""
    report: str = ""
    iteration: int = 0
    bootstrap: bool = False

    # Logs & errors
    logs: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def log(self, message: str) -> None:
        """Log a message to both the console and the internal log list."""
        from core.logger import log

        log.info(message)
        self.logs.append(message)

    @property
    def has_errors(self) -> bool:
        """Whether any agent has reported an error."""
        return len(self.errors) > 0

    def summary(self) -> str:
        """Return a one-line summary of the current context state."""
        decision_action = self.decision.get("action", "?")
        backtest_code = self.backtest.get("returncode", "?")
        n_errors = len(self.errors)
        return (
            f"[iter={self.iteration} "
            f"decision={decision_action} "
            f"backtest_code={backtest_code} "
            f"errors={n_errors}]"
        )
