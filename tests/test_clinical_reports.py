"""Kimi report trust boundary, errors and at-most-one dispatch per run."""

import copy
from io import BytesIO
import json
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from phage_lab.clinical_reports import ReportService, prepare_summary


def snapshot():
    ids = ['sample', 'isolate', 'phage', 'antibiotic', 'prepare', 'design', 'test', 'learn']
    data = {
        'schema': 'clinical-workflow-presentation-v1', 'run_id': 'demo-run-001',
        'simulated': True, 'execution_mode': 'presentation_only',
        'physical_execution': False, 'evidence_class': 'none',
        'probabilities': 'not_estimated', 'scenario_day': 13, 'case_id': 'mixed',
        'sample': {'sample_id': 'DEMO-001', 'sample_type': '模拟样本', 'collected_at': '2026-10-17T09:00'},
        'nodes': [{'id': n, 'status': 'succeeded', 'output': {}} for n in ids],
    }
    data['nodes'][1]['output'] = {'isolates': [{'id': 'ISO-001', 'name': '模拟菌', 'species': 'Demo bacterium', 'library_key': 'unused'}]}
    for n in data['nodes'][2:4]:
        n['output'] = {'matches': [{'isolate_id': 'ISO-001', 'name': '模拟菌', 'candidates': ['DEMO-01'], 'probability': 'not_estimated'}]}
    return data


def response(model='k3', finish='stop'):
    content = {'summary': '模拟样本流程已完成，尚无临床疗效证据。',
               'sections': [{'heading': title, 'content': '仅根据模拟输入整理；需医师复核。'} for title in ['样本概况', '细菌分离', '候选匹配', '证据边界', '复核事项']]}
    return BytesIO(json.dumps({'model': model, 'choices': [{'finish_reason': finish,
                              'message': {'content': json.dumps(content, ensure_ascii=False)}}]}).encode())


def wait(service, job):
    for _ in range(200):
        result = service.get(job['id'])
        if result['status'] in {'succeeded', 'failed'}:
            return result
        time.sleep(.005)
    raise AssertionError('report job did not finish')


class ReportTests(unittest.TestCase):
    def configured(self):
        service = ReportService()
        service.configure({'api_key': 'test-secret-key'})
        return service

    def test_requires_terminal_snapshot_and_preserves_honest_evidence(self):
        data = snapshot()
        data['raw_fasta'] = '>PRIVATE\nAAAA'
        data['sample']['patient_name'] = 'PRIVATE'
        summary = prepare_summary(data)
        encoded = json.dumps(summary)
        self.assertNotIn('PRIVATE', encoded)
        self.assertEqual(summary['evidence_class'], 'none')
        self.assertEqual(summary['probabilities'], 'not_estimated')
        for field, value in [('physical_execution', True), ('simulated', False)]:
            invalid = copy.deepcopy(data)
            invalid[field] = value
            with self.assertRaises(ValueError):
                prepare_summary(invalid)
        data['nodes'][-1]['status'] = 'running'
        with self.assertRaises(ValueError):
            prepare_summary(data)

    def test_rejects_untrusted_lineage_duplicate_nodes_and_invalid_candidates(self):
        for change in ['duplicate', 'mismatched_isolate', 'raw_candidate']:
            data = snapshot()
            if change == 'duplicate': data['nodes'][-1]['id'] = 'sample'
            if change == 'mismatched_isolate': data['nodes'][2]['output']['matches'][0]['isolate_id'] = 'OTHER'
            if change == 'raw_candidate': data['nodes'][2]['output']['matches'][0]['candidates'] = [{'secret': 'hidden'}]
            with self.subTest(change=change), self.assertRaises(ValueError):
                prepare_summary(data)

    def test_only_sends_minimized_data_to_fixed_k3_endpoint_and_returns_provenance(self):
        service = self.configured()
        with patch('phage_lab.clinical_reports.urlopen', return_value=response()) as request:
            result = wait(service, service.start(snapshot()))
        self.assertEqual(result['status'], 'succeeded')
        sent = request.call_args.args[0]
        self.assertEqual(sent.full_url, 'https://api.kimi.com/coding/v1/chat/completions')
        self.assertEqual(json.loads(sent.data)['model'], 'k3')
        self.assertNotIn('test-secret-key', json.dumps(result))
        self.assertEqual(result['report']['model'], 'k3')
        self.assertEqual(len(result['report']['input_sha256']), 64)
        self.assertTrue(result['report']['generated_at'])

    def test_unconfigured_errors_do_not_dispatch_and_status_never_returns_key(self):
        service = ReportService()
        with patch('phage_lab.clinical_reports.urlopen') as request:
            with self.assertRaises(ValueError): service.start(snapshot())
            request.assert_not_called()
        service.configure({'api_key': 'test-secret-key'})
        self.assertTrue(service.configuration()['configured'])
        self.assertNotIn('test-secret-key', json.dumps(service.configuration()))
        service.configure({'clear': True})
        self.assertFalse(service.configuration()['configured'])

    def test_same_run_is_idempotent_and_only_one_job_runs_at_a_time(self):
        service, gate = self.configured(), threading.Event()
        def delayed(*args, **kwargs):
            gate.wait(2)
            return response()
        with patch('phage_lab.clinical_reports.urlopen', side_effect=delayed) as request:
            a = service.start(snapshot())
            b = service.start(snapshot())
            self.assertEqual(a['id'], b['id'])
            other = snapshot(); other['run_id'] = 'other-run'
            with self.assertRaises(RuntimeError): service.start(other)
            with self.assertRaises(RuntimeError): service.configure({'clear': True})
            gate.set()
            wait(service, a)
            self.assertEqual(request.call_count, 1)

    def test_upstream_and_malformed_responses_fail_without_secret_leak_or_retry(self):
        cases = [HTTPError('https://api.kimi.com', 401, 'test-secret-key', {}, BytesIO(b'test-secret-key')),
                 response(finish='length'), response(model='kimi-for-coding'), BytesIO(b'{}')]
        for upstream in cases:
            with self.subTest(upstream=type(upstream).__name__):
                service = self.configured()
                options = {'side_effect': upstream} if isinstance(upstream, Exception) else {'return_value': upstream}
                with patch('phage_lab.clinical_reports.urlopen', **options) as request:
                    job = service.start(snapshot())
                    result = wait(service, job)
                    self.assertEqual(result['status'], 'failed')
                    self.assertNotIn('test-secret-key', json.dumps(result))
                    self.assertEqual(service.start(snapshot())['id'], job['id'])
                    self.assertEqual(request.call_count, 1)

    def test_stopped_review_snapshot_does_not_claim_completion(self):
        data = snapshot()
        data['scenario_day'] = 3
        for node in data['nodes'][2:4]:
            node['status'] = 'review'
            node['output']['matches'][0]['candidates'] = []
        for node in data['nodes'][4:]:
            node['status'] = 'blocked'; node['output'] = None
        summary = prepare_summary(data)
        self.assertEqual(summary['workflow_status'], 'needs_review')
        self.assertEqual(summary['matches']['phage'][0]['candidates'], [])

    def test_invalid_status_types_are_validation_errors(self):
        data = snapshot()
        data['nodes'][-1]['status'] = ['succeeded']
        with self.assertRaises(ValueError): prepare_summary(data)

    def test_detection_summary_retains_uncalibrated_support_but_never_fragment_bases(self):
        data = snapshot()
        record = {'id':'DET-001', 'isolate_id':'ISO-001', 'classification':'candidate_species', 'species_assignment':'Demo bacterium',
            'metrics':{'unique_reads':100, 'control_reads':10, 'covered_bases':150, 'reference_window_bp':300, 'identity_percent':98.3},
            'confidence':{'score':49.2, 'method':'synthetic-support-v1', 'calibrated':False, 'clinical_probability':None},
            'fragments':[{'id':'FRAG-DEMO-A', 'length_bp':60,'matched_bases':59,'sequence':'PRIVATE_BASES'},
                         {'id':'FRAG-DEMO-B', 'length_bp':60,'matched_bases':59,'reference_sequence':'PRIVATE_REFERENCE'}]}
        data['nodes'][1]['output']['detection'] = {'method':'synthetic-mngs-v1','simulated':True,'identified':[record],'unclassified':[]}
        summary = prepare_summary(data)
        self.assertEqual(summary['detection']['identified'][0]['confidence']['score'], 49.2)
        self.assertNotIn('PRIVATE', json.dumps(summary))
        self.assertFalse(summary['detection']['identified'][0]['confidence']['calibrated'])
        record['confidence']['clinical_probability'] = .99
        with self.assertRaises(ValueError): prepare_summary(data)

    def test_manual_retry_is_explicit_and_configuration_invalidates_cached_drafts(self):
        service = self.configured()
        with patch('phage_lab.clinical_reports.urlopen', return_value=BytesIO(b'{}')):
            failed = wait(service, service.start(snapshot()))
        with patch('phage_lab.clinical_reports.urlopen', side_effect=lambda *a, **k: response()) as request:
            retried = wait(service, service.start(snapshot(), retry=True))
            self.assertEqual(retried['status'], 'succeeded')
            self.assertNotEqual(failed['id'], retried['id'])
            service.configure({'api_key': 'another-test-secret'})
            renewed = wait(service, service.start(snapshot()))
            self.assertNotEqual(renewed['id'], retried['id'])
            self.assertEqual(request.call_count, 2)
