"""Harbor install-only harness for baseline/LSP checks; never runs a model."""
from pathlib import Path

from harbor.agents.installed.pi import Pi
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext


class PiNoModelProbe(Pi):
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        raise RuntimeError("PiNoModelProbe requires install_only=true; model execution is disabled")

    async def install(self, environment: BaseEnvironment) -> None:
        await super().install(environment)
        source = Path(__file__).parent
        for name in ("pi_load_audit.ts", "pi_lsp_probe.mjs"):
            await environment.upload_file(source / name, f"/tmp/{name}")
        await self.exec_as_agent(
            environment,
            command="mkdir -p /logs/agent/probes /tmp/harbor-pi-agent",
        )
        await self._probe(environment, "baseline")
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
        await self._probe(environment, "lsp")

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
