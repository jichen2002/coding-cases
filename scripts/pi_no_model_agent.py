"""Harbor installation and model-free component validation entry points."""
import json
from pathlib import Path

from pydantic import Field, field_validator
from harbor.agents.installed.pi import Pi, PiOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from scripts.pi_components import AGENT_DIR, install_components, manifest, resolve


class PiComponentOptions(PiOptions):
    components: list[str] = Field(default_factory=list)

    @field_validator("components")
    @classmethod
    def validate_components(cls, components: list[str]) -> list[str]:
        return resolve(components)


class PiNoModelProbeOptions(PiComponentOptions):
    @field_validator("components")
    @classmethod
    def enforce_test_policy(cls, components: list[str]) -> list[str]:
        return resolve(components, for_probe=True)


class PiComponentInstaller(Pi):
    """Explicit installation only. No load/capability checks or model execution."""
    options_model = PiComponentOptions
    options: PiComponentOptions

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        raise RuntimeError("This entry point requires install_only=true; model execution is disabled")

    async def install(self, environment: BaseEnvironment) -> None:
        self.selection = manifest(self.options.components)
        reports = self.logs_dir / "probes"
        reports.mkdir(parents=True, exist_ok=True)
        self.selection_path = reports / "selection.json"
        self.selection_path.write_text(json.dumps(self.selection, indent=2) + "\n")
        # Enforce the same config root for native Pi, package installation, and probes.
        if self._get_env("PI_CODING_AGENT_DIR") != AGENT_DIR:
            raise ValueError(f"PI_CODING_AGENT_DIR must be {AGENT_DIR}")
        await super().install(environment)
        await install_components(self, environment, self.options.components)
        self.selection["installation"] = "completed"
        self.selection_path.write_text(json.dumps(self.selection, indent=2) + "\n")


class PiNoModelProbe(PiComponentInstaller):
    options_model = PiNoModelProbeOptions
    options: PiNoModelProbeOptions

    async def install(self, environment: BaseEnvironment) -> None:
        await super().install(environment)
        source = Path(__file__).parent
        for name in ("pi_load_audit.ts", "pi_lsp_probe.mjs"):
            await environment.upload_file(source / name, f"/tmp/{name}")
        await environment.upload_file(self.selection_path, "/tmp/pi-component-manifest.json")
        variant = self.selection["variant"]
        prefix = '. "$HOME/.nvm/nvm.sh"; export PATH="/opt/miniconda3/envs/testbed/bin:$PATH"; '
        await self.exec_as_agent(environment, command="mkdir -p /logs/agent/probes")
        await self.exec_as_agent(environment, command=(
            prefix + f"PI_PROBE_OUTPUT=/logs/agent/probes/{variant}-cli.json "
            "pi --mode rpc --session-dir /tmp/pi-probe-sessions --extension /tmp/pi_load_audit.ts </dev/null"
        ), timeout_sec=90)
        await self.exec_as_agent(environment, command=(
            prefix + f"node /tmp/pi_lsp_probe.mjs --variant {variant} "
            f"--output /logs/agent/probes/{variant}-sdk.json --case-root /testbed "
            "--manifest /tmp/pi-component-manifest.json"
        ), timeout_sec=180)
        self.selection["verification"] = "passed"
        self.selection_path.write_text(json.dumps(self.selection, indent=2) + "\n")
