import base64
import hashlib
import hmac
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from .utils import get_recall_bot_recording_url, verify_recall_signature


class RecallSignatureTests(SimpleTestCase):
    def _headers_for(self, body, secret='whsec_c2VjcmV0LWtleQ==', svix=False):
        msg_id = 'msg_test'
        timestamp = '1778236105'
        secret_bytes = base64.b64decode(secret.removeprefix('whsec_'))
        signed_payload = f'{msg_id}.{timestamp}.{body.decode("utf-8")}'.encode('utf-8')
        signature = base64.b64encode(
            hmac.new(secret_bytes, signed_payload, hashlib.sha256).digest()
        ).decode('ascii')

        if svix:
            return {
                'svix-id': msg_id,
                'svix-timestamp': timestamp,
                'svix-signature': f'v1,{signature}',
            }

        return {
            'webhook-id': msg_id,
            'webhook-timestamp': timestamp,
            'webhook-signature': f'v1,{signature}',
        }

    @override_settings(RECALL_AI_WEBHOOK_SECRET='whsec_c2VjcmV0LWtleQ==')
    def test_verify_recall_signature_accepts_valid_webhook_headers(self):
        body = b'{"event":"bot.done"}'

        self.assertTrue(verify_recall_signature(body, self._headers_for(body)))

    @override_settings(
        RECALL_AI_WEBHOOK_SECRET='',
        RECALL_SVIX_WEBHOOK_SECRET='whsec_c2VjcmV0LWtleQ==',
    )
    def test_verify_recall_signature_accepts_svix_headers(self):
        body = b'{"event":"bot.done"}'

        self.assertTrue(verify_recall_signature(body, self._headers_for(body, svix=True)))

    @override_settings(RECALL_AI_WEBHOOK_SECRET='whsec_c2VjcmV0LWtleQ==')
    def test_verify_recall_signature_rejects_body_only_hex_hmac(self):
        body = b'{"event":"bot.done"}'
        legacy_signature = hmac.new(
            b'secret-key',
            body,
            hashlib.sha256,
        ).hexdigest()

        self.assertFalse(
            verify_recall_signature(
                body,
                {'X-Recall-Signature-256': f'sha256={legacy_signature}'},
            )
        )


class RecallRecordingUrlTests(SimpleTestCase):
    @override_settings(RECALL_AI_API_KEY='recall-api-key')
    @patch('apps.consultations.utils.requests.get')
    def test_get_recall_bot_recording_url_skips_null_media_shortcuts(self, mock_get):
        response = Mock()
        response.json.return_value = {
            'recordings': [
                {
                    'media_shortcuts': {
                        'audio_mixed': None,
                        'video_mixed': {
                            'data': {
                                'download_url': 'https://example.com/recording.mp4',
                            },
                        },
                    },
                },
            ],
        }
        mock_get.return_value = response

        self.assertEqual(
            get_recall_bot_recording_url('bot_123'),
            'https://example.com/recording.mp4',
        )
        response.raise_for_status.assert_called_once()

    @override_settings(RECALL_AI_API_KEY='recall-api-key')
    @patch('apps.consultations.utils.requests.get')
    def test_get_recall_bot_recording_url_reports_pending_media(self, mock_get):
        response = Mock()
        response.json.return_value = {
            'recordings': [
                {
                    'id': 'recording_123',
                    'status': {'code': 'done'},
                    'media_shortcuts': {
                        'video_mixed': {
                            'status': {'code': 'processing'},
                            'data': None,
                        },
                    },
                },
            ],
        }
        mock_get.return_value = response

        with self.assertRaisesMessage(ValueError, 'video_mixed_status'):
            get_recall_bot_recording_url('bot_123')
