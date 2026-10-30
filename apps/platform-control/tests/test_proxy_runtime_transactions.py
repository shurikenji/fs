import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.app import _build_proxy_endpoint_fields, _run_proxy_runtime_transaction  # noqa: E402


class ProxyRuntimeTransactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_proxy_runtime_transaction_marks_success(self):
        mutate = AsyncMock()

        with (
            patch('app.app.get_proxy_endpoints', AsyncMock(return_value=[{'id': 'sv1'}, {'id': 'sv2'}])),
            patch('app.app.create_deploy_job', AsyncMock(return_value=42)),
            patch('app.app.apply_proxy_state', AsyncMock(return_value={'ok': True, 'jobId': 'runtime-1'})),
            patch('app.app.mark_deploy_job_finished', AsyncMock()) as mark_finished,
        ):
            outcome = await _run_proxy_runtime_transaction(
                job_type='proxy_save_apply',
                request_payload={'endpoint_id': 'sv3'},
                mutate=mutate,
            )

        mutate.assert_awaited_once()
        mark_finished.assert_awaited_once_with(
            42,
            'success',
            response_payload={'ok': True, 'jobId': 'runtime-1'},
        )
        self.assertEqual(outcome['job_id'], 42)
        self.assertEqual(outcome['active_count'], 2)

    async def test_run_proxy_runtime_transaction_keeps_desired_state_on_apply_failure(self):
        mutate = AsyncMock()

        with (
            patch('app.app.get_proxy_endpoints', AsyncMock(return_value=[{'id': 'sv1'}])),
            patch('app.app.create_deploy_job', AsyncMock(return_value=77)),
            patch('app.app.apply_proxy_state', AsyncMock(side_effect=RuntimeError('health probe failed'))),
            patch('app.app.mark_deploy_job_finished', AsyncMock()) as mark_finished,
        ):
            with self.assertRaisesRegex(RuntimeError, 'health probe failed'):
                await _run_proxy_runtime_transaction(
                    job_type='proxy_toggle_apply',
                    request_payload={'endpoint_id': 'sv3', 'status': 'inactive'},
                    mutate=mutate,
                )

        mutate.assert_awaited_once()
        mark_finished.assert_awaited_once()
        args, kwargs = mark_finished.await_args
        self.assertEqual(args[0], 77)
        self.assertEqual(args[1], 'failed')
        self.assertIn('health probe failed', kwargs['error_message'])


class ProxyFieldNormalizationTests(unittest.TestCase):
    def test_blank_source_id_stays_none(self):
        fields = _build_proxy_endpoint_fields(
            source_id=None,
            name=' SV3 ',
            domain='SV3.SHUPREMIUM.COM ',
            target_host=' upstream.example.com ',
            target_protocol='https',
            tls_skip_verify=False,
            port=4003,
            status='active',
        )

        self.assertIsNone(fields['source_id'])
        self.assertEqual(fields['name'], 'SV3')
        self.assertEqual(fields['domain'], 'sv3.shupremium.com')
        self.assertEqual(fields['target_host'], 'upstream.example.com')
        self.assertEqual(fields['tls_skip_verify'], 0)

    def test_route_policy_is_serialized_for_operator(self):
        fields = _build_proxy_endpoint_fields(
            source_id='gemini',
            name='Gemini',
            domain='gemini.example.com',
            target_host='upstream.example.com',
            target_protocol='https',
            tls_skip_verify=False,
            port=4010,
            status='active',
            route_presets=['gemini_native', 'gemini_openai_compatible'],
            custom_route_prefixes=['/vendor/custom/'],
        )

        self.assertEqual(fields['max_body_size'], '600m')
        self.assertIn('gemini_native', fields['route_presets_json'])
        self.assertIn('/vendor/custom/', fields['custom_route_prefixes_json'])

    def test_body_size_requires_an_nginx_unit(self):
        with self.assertRaisesRegex(ValueError, 'max_body_size'):
            _build_proxy_endpoint_fields(
                source_id='bad-size',
                name='Bad size',
                domain='bad-size.example.com',
                target_host='upstream.example.com',
                target_protocol='https',
                tls_skip_verify=False,
                port=4011,
                status='active',
                max_body_size='600',
            )


if __name__ == '__main__':
    unittest.main()
