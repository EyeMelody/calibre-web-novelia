import importlib.util
import logging
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

# Small stand-ins for the host's records; no CWA server required for unit tests.
class Record:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

class Metadata:
    active = True

cps = types.ModuleType('cps')
cps.logger = types.SimpleNamespace(create=lambda: logging.getLogger('novelia-test'))
sys.modules['cps'] = cps
sys.modules['cps.services'] = types.ModuleType('cps.services')
module = types.ModuleType('cps.services.Metadata')
module.Metadata, module.MetaRecord, module.MetaSourceInfo = Metadata, Record, Record
sys.modules[module.__name__] = module
spec = importlib.util.spec_from_file_location('novelia', Path(__file__).resolve().parents[1] / 'novelia.py')
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

SAMPLE = dict(titleJp='原文タイトル', titleZh='中文书名', introductionJp='原文紹介',
              introductionZh='中文简介', authors=[{'name': '作者'}], type='已完结', keywords=['冒险'])

class Tests(unittest.TestCase):
    def setUp(self):
        plugin._CACHE.clear()
        self.p = plugin.Novelia()
        self.env = patch.dict(os.environ, {'NOVELIA_ACCESS_TOKEN': '', 'NOVELIA_BASE_URL': 'https://n.novelia.cc'})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_env_only(self):
        with patch.dict(os.environ, {'NOVELIA_TOKEN': 'ignored', 'NOVELIA_TOKEN_FILE': 'missing'}):
            self.assertEqual(self.p._token(), '')
            with patch.dict(os.environ, {'NOVELIA_ACCESS_TOKEN': 'Bearer example'}):
                self.assertEqual(self.p._token(), 'example')

    def test_two_versions(self):
        with patch.object(self.p, '_fetch', return_value=SAMPLE):
            zh, jp = self.p.search('hameln/123')
        self.assertEqual((zh.title, jp.title), ('中文书名', '原文タイトル'))
        self.assertNotEqual(zh.id, jp.id)
        self.assertEqual(zh.identifiers, jp.identifiers)
        self.assertIn('中文简介', zh.description)
        self.assertIn('原文紹介', jp.description)
        self.assertEqual(zh.description, '<p>中文简介</p>')
        self.assertEqual(jp.description, '<p>原文紹介</p>')
        self.assertNotIn('中文简介', jp.description)
        for record in (zh, jp):
            self.assertTrue({'机翻', '轻小说机翻网', 'WEB版', '已完结'} <= set(record.tags))
            self.assertNotIn('条目类型', record.description)
            self.assertNotIn('元数据来源', record.description)

    def test_missing_translation(self):
        with patch.object(self.p, '_fetch', return_value=dict(SAMPLE, titleZh=None)):
            records = self.p.search('hameln/123')
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].id.endswith(':original'))

    def test_wenku_missing_original_intro(self):
        sample = dict(title='原文タイトル', titleZh='中文书名', introduction='中文简介', authors=['作者'])
        with patch.object(self.p, '_fetch', return_value=sample):
            zh, jp = self.p.search('wenku/123')
        self.assertIn('文库版', zh.tags)
        self.assertNotIn('中文简介', jp.description)
        self.assertIsNone(zh.publishedDate)
        self.assertEqual(jp.description, '')
        self.assertEqual(zh.cover, '')

    def test_authenticated_filters(self):
        with patch.dict(os.environ, {'NOVELIA_ACCESS_TOKEN': 'example'}), patch.object(self.p, '_request_json', return_value={'items': []}) as request:
            self.assertEqual(self.p.search('书名'), [])
        self.assertEqual(request.call_count, 2)
        for call in request.call_args_list:
            self.assertEqual(call.kwargs['params']['level'], 0)
            self.assertEqual(call.kwargs['token'], 'example')

    def test_search_flattens_versions(self):
        def request(url, **kwargs):
            return {'items': [{'id': '456'}]} if url.endswith('/wenku') else {'items': [{'providerId': 'hameln', 'novelId': '123'}]}
        with patch.object(self.p, '_request_json', side_effect=request), patch.object(self.p, '_fetch', return_value=dict(SAMPLE, title='原文タイトル')):
            records = self.p.search('书名')
        self.assertEqual(len(records), 4)
        self.assertEqual(len({r.id for r in records}), 4)

    def test_refuse_foreign_origin(self):
        with patch.object(plugin.requests, 'get') as get:
            with self.assertRaises(ValueError):
                self.p._request_json('https://example.com/api')
            get.assert_not_called()

    def test_html_escape_and_tag_limit(self):
        record = self.p._record('https://n.novelia.cc', 'hameln', '123', dict(SAMPLE, introductionZh='<script>x</script>', keywords=[str(i) for i in range(100)]))
        self.assertNotIn('<script>', record.description)
        self.assertEqual(len(record.tags), 60)
        self.assertTrue({'机翻', '轻小说机翻网', 'WEB版', '已完结'} <= set(record.tags))

if __name__ == '__main__':
    unittest.main()
