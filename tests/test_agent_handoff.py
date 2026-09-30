from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentHandoffTests(unittest.TestCase):
    def test_local_material_creates_pending_queue_without_claiming_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'input.md'
            source.write_text('# Example\n\nThis is source evidence, not a completed summary.\n', encoding='utf-8')
            config = root / 'config.yaml'
            config.write_text('theme: test\n', encoding='utf-8')
            output = root / 'output'
            result = subprocess.run([
                sys.executable, str(ROOT / 'tools/podcast/scripts/fetch_podcasts.py'),
                '--config', str(config), '--output-dir', str(output),
                '--input-file', str(source), '--agent-handoff',
            ], capture_output=True, text=True, encoding='utf-8', check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload['items_summarized'], 0)
            self.assertEqual(payload['items_pending_agent'], 1)
            queue = json.loads((output / 'agent-handoff.json').read_text(encoding='utf-8'))
            task = next(iter(queue['tasks'].values()))
            self.assertEqual(task['status'], 'pending_agent')
            self.assertTrue(Path(task['raw_path']).is_file())
            page = Path(task['source_pages'][0]).read_text(encoding='utf-8')
            self.assertIn('summary_status: pending_agent', page)
            self.assertIn('confidence: low', page)

            page_path = Path(task['source_pages'][0])
            page_path.write_text('Reviewed by current agent', encoding='utf-8')
            task['status'] = 'completed_agent'
            (output / 'agent-handoff.json').write_text(json.dumps(queue), encoding='utf-8')
            again = subprocess.run(result.args, capture_output=True, text=True,
                                   encoding='utf-8', check=False)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(json.loads(again.stdout)['items_pending_agent'], 0)
            self.assertEqual(page_path.read_text(encoding='utf-8'), 'Reviewed by current agent')
