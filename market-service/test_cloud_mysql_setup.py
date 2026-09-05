import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import check_cloud_mysql


class CloudMySqlSetupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ca = Path(self.directory.name) / 'ca.pem'
        self.ca.write_text('synthetic certificate', encoding='utf-8')
        self.url = 'mysql://avnadmin:private%40value@cloud.example:13837/defaultdb'

    @patch('check_cloud_mysql.ssl.create_default_context')
    def test_verified_url_replaces_conflicting_tls_options(self, context):
        result = check_cloud_mysql.verified_mysql_url(
            self.url + '?ssl-mode=DISABLED&ssl=false&ssl-ca=old.pem&charset=utf8mb4', self.ca
        )
        parsed = urlsplit(result)
        query = parse_qs(parsed.query)
        self.assertEqual('VERIFY_IDENTITY', query['ssl-mode'][0])
        self.assertEqual(str(self.ca.resolve()), query['ssl-ca'][0])
        self.assertEqual('utf8mb4', query['charset'][0])
        self.assertNotIn('ssl', query)
        self.assertEqual('avnadmin:private%40value@cloud.example:13837', parsed.netloc)
        context.assert_called_once_with(cafile=str(self.ca.resolve()))

    def test_incomplete_placeholder_and_local_urls_are_rejected(self):
        for url in (
            '',
            'postgresql://user:secret@example.invalid/database',
            'mysql://CLICK_TO_REVEAL_PASSWORD@example.invalid/defaultdb',
            'mysql://user:secret@localhost/database',
            'mysql://user:secret@127.0.0.1/database',
            'mysql://user:secret@example.invalid/',
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    check_cloud_mysql.verified_mysql_url(url, self.ca)

    @patch('check_cloud_mysql.Database')
    @patch('check_cloud_mysql.ssl.create_default_context')
    def test_connection_check_uses_only_reads_and_never_initializes_schema(self, context, factory):
        connection = MagicMock()
        factory.return_value.connect.return_value.__enter__.return_value = connection
        cursor = connection.cursor.return_value
        cursor.fetchone.side_effect = [('8.4.8', 'defaultdb'), ('Ssl_cipher', 'TLS_AES_256_GCM_SHA384'), (0,)]
        report = check_cloud_mysql.check_connection(self.url, self.ca)
        self.assertEqual('connected', report['status'])
        self.assertTrue(report['readOnlyCheck'])
        self.assertTrue(report['tlsVerified'])
        self.assertEqual(0, report['tableCount'])
        factory.return_value.initialize_schema.assert_not_called()
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertEqual('SET TRANSACTION READ ONLY', statements[0])
        self.assertTrue(all(sql.split()[0] in {'SET', 'SELECT', 'SHOW'} for sql in statements))
        self.assertNotIn('private', json.dumps(report))

    @patch('check_cloud_mysql.Database')
    @patch('check_cloud_mysql.ssl.create_default_context')
    def test_unencrypted_connection_fails(self, context, factory):
        connection = factory.return_value.connect.return_value.__enter__.return_value
        connection.cursor.return_value.fetchone.side_effect = [('8.4.8', 'defaultdb'), ('Ssl_cipher', '')]
        with self.assertRaisesRegex(RuntimeError, 'not encrypted'):
            check_cloud_mysql.check_connection(self.url, self.ca)

    def test_driver_error_never_prints_the_secret_uri(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['check_cloud_mysql.py', '--ca-file', str(self.ca)]), \
                patch('check_cloud_mysql.check_connection', side_effect=RuntimeError(self.url)), \
                contextlib.redirect_stderr(output):
            self.assertEqual(1, check_cloud_mysql.main())
        report = json.loads(output.getvalue())
        self.assertFalse(report['credentialsIncluded'])
        self.assertNotIn('private', output.getvalue())
        self.assertNotIn(self.url, output.getvalue())


if __name__ == '__main__':
    unittest.main()
