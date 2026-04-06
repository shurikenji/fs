import sys
import unittest
from pathlib import Path

import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.operator_client import _response_error_message  # noqa: E402


class OperatorClientErrorMessageTests(unittest.TestCase):
    def test_response_error_message_includes_step_and_details(self):
        response = httpx.Response(
            500,
            json={
                'error': 'Wildcard certificate is unavailable',
                'step': 'cert_probe',
                'details': {'path': '/etc/letsencrypt/live/shupremium-wildcard'}
            }
        )

        message = _response_error_message(response)

        self.assertIn('Wildcard certificate is unavailable', message)
        self.assertIn('step: cert_probe', message)
        self.assertIn('shupremium-wildcard', message)


if __name__ == '__main__':
    unittest.main()
