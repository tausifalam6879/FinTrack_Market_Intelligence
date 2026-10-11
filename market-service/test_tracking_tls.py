import unittest
from urllib.parse import urlparse, parse_qs
from experiment_tracking import _sqlalchemy_mysql_uri


class TrackingTlsTests(unittest.TestCase):
    def test_application_tls_keys_are_translated_without_dropping_verification(self):
        uri = _sqlalchemy_mysql_uri("mysql://user:password@host:3306/fintrack_mlflow?ssl-mode=REQUIRED&ssl-ca=%2Fetc%2Fsecrets%2Fca.pem")
        parsed = urlparse(uri)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, "mysql+pymysql")
        self.assertNotIn("ssl-mode", query)
        self.assertNotIn("ssl-ca", query)
        self.assertEqual(query["ssl_ca"], ["/etc/secrets/ca.pem"])
        self.assertEqual(query["ssl_verify_cert"], ["true"])
        self.assertEqual(query["ssl_verify_identity"], ["true"])
        self.assertEqual(parsed.path, "/fintrack_mlflow")

    def test_sqlite_uri_is_unchanged(self):
        self.assertEqual(_sqlalchemy_mysql_uri("sqlite:///tracking.db"), "sqlite:///tracking.db")

    def test_existing_driver_scheme_is_not_duplicated(self):
        uri = "mysql+pymysql://user:password@host/db?ssl_ca=%2Fca.pem"
        result = _sqlalchemy_mysql_uri(uri)
        self.assertEqual(urlparse(result).scheme, "mysql+pymysql")
        self.assertEqual(_sqlalchemy_mysql_uri(result), result)
