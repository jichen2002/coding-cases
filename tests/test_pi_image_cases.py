import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.pi_image_cases import pin_image, prepare


class ImageCasePreparationTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case = self.root / 'case-one'
        self.case.mkdir()
        (self.case / 'task.toml').write_text('[environment]\ndocker_image = "base:tag"\n\n[agent]\ntimeout_sec = 10\n')
        (self.case / 'instruction.md').write_text('original')
        self.record = {'case':'case-one','base_image':'base:tag','base_image_id':'sha256:base',
                       'image':'pi:tag','image_id':'sha256:pi'}
        self.manifest = self.root / 'manifest.json'
        self.manifest.write_text(json.dumps({'schema_version':1,'cases':{'case-one':self.record}}))
        self.template = self.root / 'template.json'
        self.template.write_text(json.dumps({'tasks':[{'path':str(self.case)}], 'agents':[
            {'import_path':'scripts.pi_no_model_agent:PiNoModelProbe','kwargs':{'components':['lsp']}}]}))

    @staticmethod
    def inspect(name):
        return {'Id': {'base:tag':'sha256:base','pi:tag':'sha256:pi'}[name]}

    def test_generates_isolated_case_and_records_provenance(self):
        with patch('scripts.pi_image_cases.image_info', side_effect=self.inspect):
            job_path = prepare(self.template, self.manifest, self.root/'out')
        job = json.loads(job_path.read_text())
        copied = Path(job['tasks'][0]['path'])
        self.assertNotEqual(copied, self.case)
        self.assertIn('docker_image = "pi:tag"', (copied/'task.toml').read_text())
        self.assertIn('[agent]\ntimeout_sec = 10', (copied/'task.toml').read_text())
        self.assertIn('docker_image = "base:tag"', (self.case/'task.toml').read_text())
        self.assertTrue(job['agents'][0]['kwargs']['preinstalled_node'])
        record = json.loads((self.root/'out/image-manifest.json').read_text())['cases']['case-one']
        self.assertEqual(record['image_id'], 'sha256:pi')
        self.assertEqual(record['source_path'], str(self.case))

    def test_rejects_changed_image_before_creating_output(self):
        def inspect(name):
            return {'Id': 'sha256:changed' if name == 'pi:tag' else 'sha256:base'}
        with patch('scripts.pi_image_cases.image_info', side_effect=inspect):
            with self.assertRaisesRegex(ValueError, 'Pi image ID changed'):
                prepare(self.template, self.manifest, self.root/'out')
        self.assertFalse((self.root/'out').exists())

    def test_rejects_changed_base_binding(self):
        pin_image(self.case, 'base:other')
        with self.assertRaisesRegex(ValueError, 'Base image binding changed'):
            prepare(self.template, self.manifest, self.root/'out')
        self.assertFalse((self.root/'out').exists())

    def test_rejects_builtin_pi_and_unselected_dataset(self):
        data = json.loads(self.template.read_text())
        data['datasets'] = [{'path': 'other'}]
        self.template.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Dataset expansion'):
            prepare(self.template, self.manifest, self.root/'out')
        del data['datasets']
        data['agents'] = [{'name': 'pi'}]
        self.template.write_text(json.dumps(data))
        with patch('scripts.pi_image_cases.image_info', side_effect=self.inspect):
            with self.assertRaisesRegex(ValueError, 'Built-in Pi'):
                prepare(self.template, self.manifest, self.root/'out')
        self.assertFalse((self.root/'out').exists())


if __name__ == '__main__':
    unittest.main()
