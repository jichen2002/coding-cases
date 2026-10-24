"""Harbor install-only harness for baseline/LSP checks; never runs a model."""
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from harbor.agents.installed.pi import Pi, PiOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext


class PiNoModelProbeOptions(PiOptions):
    components: list[Literal["lsp"]] = Field(default_factory=list)

    @field_validator("components")
    @classmethod
    def reject_duplicates(cls, components: list[str]) -> list[str]:
        if len(components) != len(set(components)):
            raise ValueError("components must not contain duplicates")
        return components


class PiNoModelProbe(Pi):
    options_model = PiNoModelProbeOptions
    options: PiNoModelProbeOptions

    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        raise RuntimeError("PiNoModelProbe requires install_only=true; model execution is disabled")

    async def install(self, environment: BaseEnvironment) -> None:
        variant = "lsp" if "lsp" in self.options.components else "baseline"
        reports = self.logs_dir / "probes"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "selection.json").write_text(
            json.dumps({"variant": variant, "components": self.options.components}, indent=2) + "\n"
        )
        await super().install(environment)
        source = Path(__file__).parent
        for name in ("pi_load_audit.ts", "pi_lsp_probe.mjs"):
            await environment.upload_file(source / name, f"/tmp/{name}")
        await self.exec_as_agent(
            environment,
            command="mkdir -p /logs/agent/probes /tmp/harbor-pi-agent",
        )
        if variant == "lsp":
            await self.exec_as_agent(
                environment,
                command=(
                    '. "$HOME/.nvm/nvm.sh"; '
                    "npm install -g --ignore-scripts pyright@1.1.413 && "
                    "pi install npm:pi-diet-lsp@0.1.9 && "
                    "pyright --version && command -v pyright-langserver && pi list"
                ),
                timeout_sec=600,
            )
        await self._probe(environment, variant)

    async def _probe(self, environment: BaseEnvironment, variant: str) -> None:
        await self.exec_as_agent(
            environment,
            command=(
                '. "$HOME/.nvm/nvm.sh"; '
                'export PATH="/opt/miniconda3/envs/testbed/bin:$PATH"; '
                f"PI_PROBE_OUTPUT=/logs/agent/probes/{variant}-cli.json "
                "pi --mode rpc --session-dir /tmp/pi-probe-sessions "
                "--extension /tmp/pi_load_audit.ts </dev/null"
            ),
            timeout_sec=90,
        )
        await self.exec_as_agent(
            environment,
            command=(
                '. "$HOME/.nvm/nvm.sh"; '
                'export PATH="/opt/miniconda3/envs/testbed/bin:$PATH"; '
                f"node /tmp/pi_lsp_probe.mjs --variant {variant} "
                f"--output /logs/agent/probes/{variant}-sdk.json --case-root /testbed"
            ),
            timeout_sec=120,
        )
