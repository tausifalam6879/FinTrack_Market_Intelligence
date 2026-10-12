"""Offline regression checks for cold pulls, timeout redaction and cleanup."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import rehearse_mysql_restore as recovery


class RecoveryStartupTests(unittest.TestCase):
    def test_cached_image_is_not_downloaded(self):
        with patch.object(recovery.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            recovery.ensure_mysql_image()
        self.assertEqual(run.call_count, 1)

    def test_cold_pull_has_separate_deadline_and_visible_progress(self):
        with patch.object(recovery.subprocess, 'run', side_effect=[subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)]) as run:
            recovery.ensure_mysql_image()
        self.assertEqual(run.call_args.args[0], ['docker', 'pull', 'mysql:8.4'])
        self.assertEqual(run.call_args.kwargs['timeout'], 600)
        self.assertNotIn('capture_output', run.call_args.kwargs)

    def test_start_timeout_is_sanitized_and_cleans_allocated_resources(self):
        calls = []
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if list(cmd[:2]) == ['docker', 'run']:
                raise subprocess.TimeoutExpired(cmd, 180)
            return subprocess.CompletedProcess(cmd, 0, b'', b'')
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / 'backup.sql'
            backup.write_bytes(b'-- synthetic test')
            backup.with_suffix('.sql.manifest.json').write_text(json.dumps({
                'format': 'mysql-sql', 'sha256': hashlib.sha256(backup.read_bytes()).hexdigest()}))
            with patch('sys.argv', ['recovery', str(backup), '--application']), \
                 patch.object(recovery.subprocess, 'run', side_effect=fake_run), \
                 self.assertRaises(SystemExit) as raised:
                recovery.main()
        self.assertNotIn('MYSQL_PASSWORD', str(raised.exception))
        start = next(c for c in calls if list(c[:2]) == ['docker', 'run'])
        self.assertIn('--pull=never', start)
        name = start[start.index('--name') + 1]
        self.assertIn(['docker', 'rm', '-f', name], calls)
        self.assertIn(['docker', 'network', 'rm', name + '-net'], calls)

    def test_cleanup_timeout_does_not_replace_original_failure(self):
        with patch.object(recovery.subprocess, 'run', side_effect=subprocess.TimeoutExpired(['docker'], 60)):
            recovery.cleanup_resource('container', 'fintrack-restore-test')


if __name__ == '__main__':
    unittest.main()
