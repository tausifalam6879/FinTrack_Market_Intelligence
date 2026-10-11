import unittest
from cloud_backup import dump_command


class CloudBackupTests(unittest.TestCase):
    def test_dump_is_transactional_tls_verified_and_password_not_in_arguments(self):
        command, env = dump_command("mysql://backup:secret%21@database.example:1234/fintrack", "/tmp/test.sql")
        self.assertIn("--single-transaction", command)
        self.assertIn("--ssl-mode=VERIFY_IDENTITY", command)
        self.assertIn("--ssl-ca=/etc/secrets/ca.pem", command)
        self.assertNotIn("secret!", " ".join(command))
        self.assertEqual(env["MYSQL_PWD"], "secret!")
        self.assertEqual(command[-1], "fintrack")

    def test_invalid_database_configuration_is_rejected(self):
        for url in ("sqlite:///tmp/test.db", "mysql://host", "mysql://user@host/"):
            with self.assertRaises(ValueError):
                dump_command(url, "/tmp/test.sql")
