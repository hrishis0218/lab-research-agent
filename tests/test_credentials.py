"""Offline tests for optional Windows credential persistence."""
import unittest
from unittest.mock import patch
from backend import credentials


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, name):
        return self.values.get((service, name))

    def set_password(self, service, name, secret):
        self.values[(service, name)] = secret

    def delete_password(self, service, name):
        del self.values[(service, name)]


class CredentialTests(unittest.TestCase):
    def test_store_read_delete(self):
        backend = FakeKeyring()
        with patch("backend.credentials._backend", return_value=backend):
            credentials.save_key("Gemini", "test-secret")
            self.assertEqual(credentials.get_key("Gemini"), "test-secret")
            credentials.delete_key("Gemini")
            self.assertEqual(credentials.get_key("Gemini"), "")

    def test_invalid_provider_and_empty_secret(self):
        with self.assertRaises(ValueError):
            credentials.get_key("unknown")
        with self.assertRaises(ValueError):
            credentials.save_key("Gemini", "")


if __name__ == "__main__":
    unittest.main()
