import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dest = self.root / 'install'
        self.codex = self.root / 'codex'
        self.codex.mkdir()
        self.dest.mkdir()
        (self.dest / '.codex-plugin').mkdir()
        (self.dest / '.codex-plugin/plugin.json').write_text('{"name":"image-api"}')
        self.python = self.dest / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        self.python.parent.mkdir(parents=True)
        self.python.touch()

    def tearDown(self):
        self.tmp.cleanup()

    def run_installer(self):
        with patch.dict(os.environ, {'CODEX_HOME': str(self.codex)}), patch.object(sys, 'argv', [
            'install.py', '--destination', str(self.dest), '--register'
        ]), patch('subprocess.run'):
            runpy.run_path(str(ROOT / 'scripts/install.py'), run_name='__main__')

    def test_conflict_does_not_modify_existing_installation(self):
        marker = self.dest / 'scripts/server.py'
        marker.parent.mkdir()
        marker.write_text('existing server')
        config = '[mcp_servers.image_api]\ncommand="another-server"\n'
        (self.codex / 'config.toml').write_text(config)
        with self.assertRaises(SystemExit):
            self.run_installer()
        self.assertEqual(marker.read_text(), 'existing server')
        self.assertEqual((self.codex / 'config.toml').read_text(), config)

    def test_managed_skill_upgrade_preserves_custom_mcp_config(self):
        previous = self.dest / 'skills/image-api/SKILL.md'
        target = self.codex / 'skills/image-api/SKILL.md'
        for path in [previous, target]:
            path.parent.mkdir(parents=True)
            path.write_text('previous managed skill')
        config = ('[mcp_servers.image_api]\ncommand=' + json.dumps(str(self.python.resolve())) + '\nargs=' +
                  json.dumps([str((self.dest / 'scripts/server.py').resolve())]) +
                  '\ntool_timeout_sec=400\n[mcp_servers.image_api.env]\nIMAGEGEN_MODEL="gpt-image-2.5-flare"\n')
        (self.codex / 'config.toml').write_text(config)
        self.run_installer()
        self.assertEqual(target.read_bytes(), (ROOT / 'skills/image-api/SKILL.md').read_bytes())
        self.assertEqual((self.codex / 'config.toml').read_text(), config)

    def test_independent_skill_edits_are_preserved(self):
        target = self.codex / 'skills/image-api/SKILL.md'
        target.parent.mkdir(parents=True)
        target.write_text('user customization')
        with self.assertRaises(SystemExit):
            self.run_installer()
        self.assertEqual(target.read_text(), 'user customization')
        self.assertFalse((self.codex / 'config.toml').exists())

    def test_fresh_registration_leaves_model_selection_to_server(self):
        self.run_installer()
        config = tomllib.loads((self.codex / 'config.toml').read_text())
        self.assertNotIn('IMAGEGEN_MODEL', config['mcp_servers']['image_api']['env'])
        plugin = json.loads((self.dest / '.mcp.json').read_text())
        self.assertNotIn('IMAGEGEN_MODEL', plugin['mcpServers']['image_api']['env'])


if __name__ == '__main__':
    unittest.main()
