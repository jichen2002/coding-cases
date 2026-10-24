"""Harbor Pi component adapter, installer-only, and model-free probe entry points."""
import json
from pathlib import Path
import shlex

from pydantic import Field, field_validator
from harbor.agents.installed.pi import Pi, PiOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from scripts.pi_components import AGENT_DIR, install_components, manifest, resolve

DEFAULT_CONTEXT_WINDOW = 262_144
DEFAULT_COMPACTION_TRIGGER_RATIO = 0.9
DEFAULT_KEEP_RECENT_TOKENS = 20_000


def compaction_settings(context_window: int, trigger_ratio: float) -> dict:
    """Build Pi settings with the reserve needed to trigger at the requested ratio."""
    reserve_tokens = round(context_window * (1 - trigger_ratio))
    return {
        "compaction": {
            "enabled": True,
            "reserveTokens": reserve_tokens,
            "keepRecentTokens": DEFAULT_KEEP_RECENT_TOKENS,
        }
    }


def set_model_context_window(models_json: dict, context_window: int) -> dict:
    """Set context metadata on the generated Harbor custom model entry."""
    for provider in models_json.get("providers", {}).values():
        for model in provider.get("models", []):
            model["contextWindow"] = context_window
    return models_json


class PiComponentOptions(PiOptions):
    components: list[str] = Field(default_factory=list)
    context_window: int = Field(default=DEFAULT_CONTEXT_WINDOW, ge=1)
    compaction_trigger_ratio: float = Field(
        default=DEFAULT_COMPACTION_TRIGGER_RATIO, gt=0, lt=1
    )

    @field_validator("components")
    @classmethod
    def validate_components(cls, components: list[str]) -> list[str]:
        return resolve(components)


class PiNoModelProbeOptions(PiComponentOptions):
    @field_validator("components")
    @classmethod
    def enforce_test_policy(cls, components: list[str]) -> list[str]:
        return resolve(components, for_probe=True)


class PiComponentAgent(Pi):
    """Run Pi with locally registered components installed into its agent dir."""
    options_model = PiComponentOptions
    options: PiComponentOptions

    def _build_custom_models_json(self, access, model_id: str):
        models_json = super()._build_custom_models_json(access, model_id)
        if models_json is not None:
            set_model_context_window(models_json, self.options.context_window)
        return models_json

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
        await self._ensure_config_dir(environment)
        settings = compaction_settings(
            self.options.context_window,
            self.options.compaction_trigger_ratio,
        )
        script = (
            "const fs=require('node:fs');"
            "const p=process.env.PI_CODING_AGENT_DIR+'/settings.json';"
            "const c=fs.existsSync(p)?JSON.parse(fs.readFileSync(p,'utf8')):{};"
            f"const incoming={json.dumps(settings)};"
            "c.compaction={...(c.compaction||{}),...incoming.compaction};"
            "fs.writeFileSync(p,JSON.stringify(c,null,2)+'\\n');"
        )
        await self.exec_as_agent(
            environment,
            command='. "$HOME/.nvm/nvm.sh"; node -e ' + shlex.quote(script),
        )
        self.selection["installation"] = "completed"
        self.selection_path.write_text(json.dumps(self.selection, indent=2) + "\n")


class PiComponentInstaller(PiComponentAgent):
    """Explicit installation only. Model execution is disabled."""

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        raise RuntimeError("This entry point requires install_only=true; model execution is disabled")


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
