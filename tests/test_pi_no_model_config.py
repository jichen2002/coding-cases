"""Validate the public Harbor preflight entry point without creating containers."""
import json
from pathlib import Path
import unittest

from harbor.models.job.config import JobConfig
from pydantic import ValidationError

from scripts.pi_no_model_agent import PiNoModelProbe
from scripts.pi_components import manifest


class ComponentConfigTest(unittest.TestCase):
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
