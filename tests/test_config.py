import unittest
import os
from backend.app.config import Settings

class TestConfig(unittest.TestCase):
    """Verifies environment-based configuration and fixed event specifications."""

    def test_default_event_specifications(self):
        """Validates the 10 rows x 12 seats = 120 total seats requirement."""
        settings = Settings()
        self.assertEqual(settings.TOTAL_ROWS, 10)
        self.assertEqual(settings.SEATS_PER_ROW, 12)
        self.assertEqual(settings.TOTAL_SEATS, 120)

    def test_hold_specifications(self):
        """Validates hold duration (5 mins) and max seat limits (4 seats)."""
        settings = Settings()
        self.assertEqual(settings.MAX_HOLD_SEATS, 4)
        self.assertEqual(settings.HOLD_DURATION_MINUTES, 5)
        self.assertEqual(settings.HOLD_DURATION_SECONDS, 300)

    def test_default_database_url_structure(self):
        """Validates MySQL URL construction using PyMySQL driver."""
        settings = Settings()
        self.assertIn("mysql+pymysql://", settings.DATABASE_URL)
        self.assertIn(f":{settings.DB_PORT}/", settings.DATABASE_URL)

    def test_custom_environment_override(self):
        """Validates that environment variables override defaults."""
        os.environ["DB_NAME"] = "test_seat_booking"
        os.environ["DB_PORT"] = "3307"
        custom_settings = Settings()
        self.assertEqual(custom_settings.DB_NAME, "test_seat_booking")
        self.assertEqual(custom_settings.DB_PORT, 3307)
        self.assertIn("test_seat_booking", custom_settings.DATABASE_URL)
        self.assertIn(":3307/", custom_settings.DATABASE_URL)
        # Cleanup
        del os.environ["DB_NAME"]
        del os.environ["DB_PORT"]

if __name__ == "__main__":
    unittest.main()
