"""Validate the public Harbor preflight entry point without creating containers."""
import json
from pathlib import Path
import unittest

from harbor.models.job.config import JobConfig
from pydantic import ValidationError

from scripts.pi_no_model_agent import PiNoModelProbe


class ComponentConfigTest(unittest.TestCase):
    def test_supported_selections_pass_harbor_preflight(self):
        for components in ([], ["lsp"]):
            with self.subTest(components=components):
                PiNoModelProbe.preflight(
                    kwargs={"version": "1.4.0", "components": components}, env={}
                )

    def test_invalid_selections_fail_before_container_creation(self):
        for components in (["ast"], ["lsp", "lsp"], "lsp", [1], None):
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


if __name__ == "__main__":
    unittest.main()
