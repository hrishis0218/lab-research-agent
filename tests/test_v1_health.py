"""First API smoke test; run `python -m unittest discover -s tests`."""
import unittest


class HealthEndpointTest(unittest.TestCase):
    def test_health_payload(self):
        try:
            from backend.main import health
        except ImportError as exc:
            self.skipTest(f"FastAPI dependencies not installed: {exc}")
        self.assertEqual(
            health(),
            {"status": "ok", "application": "Lab Research Agent", "version": "1.0.0-dev"},
        )


if __name__ == "__main__":
    unittest.main()
