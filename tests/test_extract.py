import io
import json
import unittest
from unittest.mock import patch

import arcgis
from extract import select_layer


class ArcGISTests(unittest.TestCase):
    def test_arcgis_error_is_not_empty_success(self):
        response = io.BytesIO(b'{"error":{"code":500,"message":"bad query"}}')
        with patch('arcgis.urlopen', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'bad query'):
                arcgis.fetch_json('https://example.test', retries=1)

    def test_count_mismatch_fails(self):
        with patch('arcgis.fetch_json', side_effect=[{'objectIds': [1]}, {'count': 2}]):
            with self.assertRaisesRegex(RuntimeError, 'disagree'):
                arcgis.query_ids('https://example.test')

    def test_transfer_limit_splits_batches(self):
        meta = {'objectIdField': 'FID', 'maxRecordCount': 100}
        def fetch(url, params=None):
            if params is None:
                return meta
            ids = [int(i) for i in params['objectIds'].split(',')]
            received = ids[:1]
            return {'type': 'FeatureCollection', 'exceededTransferLimit': len(ids) > 1,
                    'features': [{'properties': {'FID': i}, 'geometry': None} for i in received]}
        with patch('arcgis.query_ids', return_value=[1, 2, 3]), patch('arcgis.fetch_json', side_effect=fetch):
            result = arcgis.download('https://example.test', meta)
        self.assertEqual([f['properties']['FID'] for f in result['features']], [1, 2, 3])

    def test_missing_single_feature_fails(self):
        with patch('arcgis.query_ids', return_value=[1]), patch('arcgis.fetch_json', return_value={
                'type': 'FeatureCollection', 'features': []}):
            with self.assertRaisesRegex(RuntimeError, 'Missing'):
                arcgis.download('https://example.test', {'objectIdField': 'FID'})

    def test_truncated_json_response_splits_batch(self):
        meta = {'objectIdField': 'FID', 'maxRecordCount': 100}
        truncated = json.JSONDecodeError('truncated', '', 0)

        def fetch(url, params=None):
            if params is None:
                return meta
            ids = [int(i) for i in params['objectIds'].split(',')]
            if len(ids) > 1:
                raise truncated
            return {'type': 'FeatureCollection',
                    'features': [{'properties': {'FID': ids[0]}, 'geometry': None}]}

        with patch('arcgis.query_ids', return_value=[1, 2, 3]), patch(
                'arcgis.fetch_json', side_effect=fetch):
            result = arcgis.download('https://example.test', meta)
        self.assertEqual([f['properties']['FID'] for f in result['features']], [1, 2, 3])

    def test_source_edit_during_download_fails(self):
        meta = {'objectIdField': 'FID', 'editingInfo': {'lastEditDate': 1}}
        with patch('arcgis.query_ids', return_value=[]), patch('arcgis.fetch_json', return_value={
                **meta, 'editingInfo': {'lastEditDate': 2}}):
            with self.assertRaisesRegex(RuntimeError, 'edited'):
                arcgis.download('https://example.test', meta)

    def test_excluded_layers_and_hidden_layers(self):
        layer = {'url': 'https://example.test/MapServer/8', 'visibility': False}
        self.assertIsNone(select_layer('interim', ('IV.) Priority Housing Projects within Buffer',), layer))
        self.assertEqual(select_layer('interim', ('III.) Village Center & Buffer',), layer)['kind'], 'interim')

