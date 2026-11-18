import unittest

from backend.database.connection import check_database
from backend.database.repositories import get_statistics


class MySqlIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            check_database()
        except Exception as exc:
            errno = getattr(exc, "errno", None)
            detail = f" (MySQL error {errno})" if errno else f" ({type(exc).__name__})"
            raise unittest.SkipTest("MySQL server is unavailable" + detail) from None

    def test_database_schema_and_read_connection(self):
        stats = get_statistics()
        self.assertIsInstance(stats, dict)


if __name__ == "__main__":
    unittest.main()
