from __future__ import annotations

import traceback
from typing import Any

from core.context import Context
from core.logger import log


class DirectorError(RuntimeError):
    """Fatal Director error — pipeline cannot continue."""


class Director:

    def __init__(self, iterations: int = 3, fail_fast: bool = False, bootstrap: bool = False):
        self.pipeline: list[Any] = []
        self.iterations = iterations
        self.fail_fast = fail_fast
        self.bootstrap = bootstrap
        self.errors: list[dict[str, Any]] = []

    def register(self, agent: Any) -> None:
        self.pipeline.append(agent)

    def run(self) -> Context:
        previous_report = ""
        ctx = Context()

        for iteration in range(1, self.iterations + 1):
            log.info("{:=^60}", f" ITERATION {iteration} ")
            log.info("{:-^60}", f" Pipeline: {len(self.pipeline)} agents ")

            ctx = Context(bootstrap=self.bootstrap)
            ctx.iteration = iteration
            ctx.report = previous_report
            self.errors = []

            for agent in self.pipeline:
                agent_name = agent.__class__.__name__

                try:
                    log.info("Running agent: {}", agent_name)
                    ctx = agent.run(ctx)
                    log.info("Agent {} completed successfully", agent_name)

                except Exception as exc:
                    log.opt(exception=True).error(
                        "Agent {} failed: {}", agent_name, exc
                    )
                    err_entry = {
                        "iteration": iteration,
                        "agent": agent_name,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                    self.errors.append(err_entry)
                    ctx.errors.append(err_entry)

                    if self.fail_fast:
                        raise DirectorError(
                            f"Agent {agent_name} failed on iteration "
                            f"{iteration}: {exc}"
                        ) from exc

                    log.warning(
                        "Continuing pipeline after {} failure", agent_name
                    )

            previous_report = ctx.report

            if self.errors:
                log.warning(
                    "Iteration {} finished with {} error(s)",
                    iteration,
                    len(self.errors),
                )
            else:
                log.info("Iteration {} finished successfully", iteration)

        log.info("{:=^60}", " PIPELINE FINISHED ")
        log.info("Total errors across all iterations: {}", len(self.errors))
        return ctx
