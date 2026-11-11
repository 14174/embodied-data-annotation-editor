import io
import json
import sys
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import caption_assist


class CaptionAssistTests(unittest.TestCase):
    def call(self, content, finish='stop'):
        response = {'choices': [{'finish_reason': finish, 'message': {'content': content}}]}
        return patch('caption_assist.urlopen', return_value=io.BytesIO(json.dumps(response).encode()))

    def test_returns_suggestion_and_warnings_without_changing_input(self):
        original = 'Pick up the white garment. Put it into the dryer. Begin picking up the black garment.'
        with self.call(json.dumps({'caption': 'Place the white garment in the dryer, then begin picking up the black garment.',
                                   'warnings': ['包含下一次黑色衣物操作，请核对区间。']})) as transport:
            result = caption_assist.simplify(original, {'DASHSCOPE_API_KEY': 'test-secret',
                'DASHSCOPE_BASE_URL': 'https://example.org/compatible-mode/v1'})
        self.assertEqual(result['warnings'], ['包含下一次黑色衣物操作，请核对区间。'])
        self.assertIn('black garment', result['caption'])
        request = transport.call_args.args[0]
        sent = json.loads(request.data)
        self.assertEqual(json.loads(sent['messages'][-1]['content']), {'caption': original})
        self.assertFalse(sent['enable_thinking'])
        self.assertEqual(request.full_url, 'https://example.org/compatible-mode/v1/chat/completions')

    def test_empty_input_and_missing_configuration_never_send(self):
        with patch('caption_assist.urlopen') as transport:
            for text in ['', '  ', 'x' * 12001, None]:
                with self.assertRaises(ValueError):
                    caption_assist.simplify(text, {})
            with self.assertRaises(caption_assist.AssistUnavailable):
                caption_assist.simplify('Pick up the toy.', {})
        transport.assert_not_called()

    def test_diversify_uses_rewrite_mode_and_only_sends_current_caption(self):
        original = 'Pick up the brown stuffed toy with the left hand.'
        with self.call('{"caption":"Lift the brown plush toy using the left hand.","warnings":[]}') as transport:
            result = caption_assist.simplify(original, {'DASHSCOPE_API_KEY':'secret'}, mode='diversify')
        self.assertEqual(result['caption'], 'Lift the brown plush toy using the left hand.')
        self.assertEqual(result['mode'], 'diversify')
        sent = json.loads(transport.call_args.args[0].data)
        self.assertEqual(json.loads(sent['messages'][-1]['content']), {'caption': original})
        self.assertGreater(sent['temperature'], .1)
        self.assertFalse(sent['enable_thinking'])

    def test_unknown_mode_does_not_call_provider(self):
        with patch('caption_assist.urlopen') as transport, self.assertRaises(ValueError):
            caption_assist.simplify('Pick toy.', {'DASHSCOPE_API_KEY':'secret'}, mode='translate')
        transport.assert_not_called()

    def test_truncated_or_malformed_model_output_cannot_be_adopted(self):
        for content, finish in [('not json', 'stop'), ('{"caption":"","warnings":[]}', 'stop'),
                                ('{"caption":"Pick up toy","warnings":"no"}', 'stop'),
                                ('{"caption":"Pick up toy","warnings":[]}', 'length')]:
            with self.call(content, finish), self.assertRaises(caption_assist.AssistUnavailable):
                caption_assist.simplify('Pick up the toy.', {'DASHSCOPE_API_KEY': 'secret'})

    def test_provider_error_does_not_expose_credentials_or_response_body(self):
        error = HTTPError('https://example.org', 401, 'secret-key', {}, io.BytesIO(b'secret-body'))
        with patch('caption_assist.urlopen', side_effect=error), self.assertRaises(caption_assist.AssistUnavailable) as raised:
            caption_assist.simplify('Pick up toy.', {'DASHSCOPE_API_KEY': 'secret-key'})
        self.assertNotIn('secret', str(raised.exception))
        self.assertIn('401', str(raised.exception))

    def test_busy_server_rejects_new_calls_and_releases_slots_after_failure(self):
        entered = threading.Barrier(3)
        release = threading.Event()
        def delayed(*args, **kwargs):
            entered.wait(timeout=5)
            release.wait(timeout=5)
            raise TimeoutError()
        with patch('caption_assist.urlopen', side_effect=delayed), ThreadPoolExecutor(2) as pool:
            jobs = [pool.submit(caption_assist.simplify, 'Pick toy.', {'DASHSCOPE_API_KEY':'secret'}) for _ in range(2)]
            entered.wait(timeout=5)
            try:
                with self.assertRaisesRegex(caption_assist.AssistUnavailable, '繁忙'):
                    caption_assist.simplify('Pick toy.', {'DASHSCOPE_API_KEY':'secret'})
            finally:
                release.set()
            for job in jobs:
                with self.assertRaises(caption_assist.AssistUnavailable): job.result()
        with self.call('{"caption":"Pick toy.","warnings":[]}'):
            self.assertEqual(caption_assist.simplify('Pick toy.', {'DASHSCOPE_API_KEY':'secret'})['caption'], 'Pick toy.')


if __name__ == '__main__':
    unittest.main()
