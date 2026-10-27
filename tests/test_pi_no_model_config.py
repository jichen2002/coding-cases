"""Validate the public Harbor preflight entry point without creating containers."""
import json
from pathlib import Path
import unittest

from harbor.models.job.config import JobConfig
from pydantic import ValidationError

from scripts.pi_no_model_agent import (
    PiComponentAgent,
    PiNoModelProbe,
    compaction_settings,
    set_model_context_window,
    temperature_extension,
)
from scripts.pi_components import manifest


class ComponentConfigTest(unittest.TestCase):
    def test_model_enabled_component_agent_accepts_custom_endpoint(self):
        kwargs = {
            "version": "1.4.0",
            "components": ["lsp"],
            "model_api": "openai-completions",
        }
        PiComponentAgent.preflight(
            kwargs=kwargs,
            env={
                "OPENAI_BASE_URL": "http://127.0.0.1:8000/v1",
                "OPENAI_API_KEY": "EMPTY",
                "PI_CODING_AGENT_DIR": "/tmp/harbor-pi-agent",
            },
        )
        options = PiComponentAgent.options_model.model_validate(kwargs)
        self.assertEqual(options.components, ["lsp"])
        self.assertEqual(options.model_api, "openai-completions")
        self.assertEqual(options.context_window, 262144)
        self.assertEqual(options.compaction_trigger_ratio, 0.9)

    def test_temperature_is_validated_and_extension_pins_request_payload(self):
        options = PiComponentAgent.options_model.model_validate({"temperature": 0.6})
        self.assertEqual(options.temperature, 0.6)
        source = temperature_extension(0.6)
        self.assertIn('pi.on("before_provider_request"', source)
        self.assertIn("temperature: 0.6", source)
        self.assertIn("pi-temperature-requests.jsonl", source)
        for invalid in (-0.1, 2.1):
            with self.subTest(temperature=invalid):
                with self.assertRaises(ValidationError):
                    PiComponentAgent.options_model.model_validate(
                        {"temperature": invalid}
                    )

    def test_pi_context_and_compaction_defaults_are_written_explicitly(self):
        settings = compaction_settings(262144, 0.9)
        self.assertEqual(
            settings,
            {
                "compaction": {
                    "enabled": True,
                    "reserveTokens": 26214,
                    "keepRecentTokens": 20000,
                }
            },
        )
        model = {"providers": {"harbor-endpoint": {"models": [{"id": "Qwen3.5-9B"}]}}}
        configured = set_model_context_window(model, 262144)
        self.assertEqual(
            configured["providers"]["harbor-endpoint"]["models"][0]["contextWindow"],
            262144,
        )

    def test_supported_selections_pass_harbor_preflight(self):
        for components in ([], ["lsp"], ["ast-search"], ["todo"], ["skills"], ["lsp", "skills"]):
            with self.subTest(components=components):
                PiNoModelProbe.preflight(
                    kwargs={"version": "1.4.0", "components": components}, env={}
                )

    def test_invalid_selections_fail_before_container_creation(self):
        for components in (["ast"], ["plan"], ["lsp", "lsp"], "lsp", [1], None):
            with self.subTest(components=components):
                with self.assertRaises((ValueError, ValidationError)):
                    PiNoModelProbe.preflight(
                        kwargs={"version": "1.4.0", "components": components}, env={}
                    )

    def test_example_defines_two_separate_agent_selections(self):
        path = Path(__file__).resolve().parents[1] / "experiments/pi-lsp-no-model.json"
        config = JobConfig.model_validate(json.loads(path.read_text()))
        self.assertTrue(config.install_only)
        self.assertEqual(config.n_attempts, 1)
        self.assertEqual(len(config.tasks), 1)
        self.assertEqual([agent.kwargs["components"] for agent in config.agents], [[], ["lsp"]])
        for agent in config.agents:
            PiNoModelProbe.preflight(kwargs=agent.kwargs, env={})
        self.assertIn("HTTPS_PROXY", config.verifier.env)
        for key in ("NO_PROXY", "no_proxy"):
            self.assertIn("10.0.0.0/8", config.agents[0].env[key])
            self.assertIn("172.16.0.0/12", config.verifier.env[key])
            self.assertIn("192.168.0.0/16", config.agents[1].env[key])
            self.assertIn("169.254.0.0/16", config.verifier.env[key])

    def test_extended_example_only_runs_allowed_probes(self):
        path = Path(__file__).resolve().parents[1] / "experiments/pi-components-no-model.json"
        config = JobConfig.model_validate(json.loads(path.read_text()))
        self.assertEqual([a.kwargs["components"] for a in config.agents],
                         [[], ["lsp"], ["ast-search"], ["todo"], ["skills"], ["lsp", "skills"]])
        for agent in config.agents:
            PiNoModelProbe.preflight(kwargs=agent.kwargs, env={})

    def test_combination_has_canonical_name_and_merged_expectations(self):
        result = manifest(["skills", "lsp"])
        self.assertEqual(result["variant"], "lsp+skills")
        self.assertEqual(result["components"], ["lsp", "skills"])
        self.assertEqual(result["expectedSkills"], ["diagnosing-bugs", "tdd"])
        self.assertEqual(result["expectedExtensions"], 1)
        self.assertIn("lsp_definition", result["expectedTools"])
        self.assertEqual(result["verification"], "not_tested")


if __name__ == "__main__":
    unittest.main()
