import importlib.util
import datetime
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('manager', Path(__file__).resolve().parents[1] / 'manager.py')
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ACCOUNT_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
ACCOUNT_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
ORG_A = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'
ORG_B = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd'
SESSION_1 = '11111111-1111-4111-8111-111111111111'
SESSION_2 = '22222222-2222-4222-8222-222222222222'
SESSION_3 = '33333333-3333-4333-8333-333333333333'
ACCOUNT_C = 'cccccccc-1111-4111-8111-111111111111'
ORG_C = 'dddddddd-1111-4111-8111-111111111111'


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patch_data = mock.patch.object(m, 'DATA', {'a': root / 'a', 'b': root / 'b'})
        self.patch_state = mock.patch.object(m, 'STATE', root / 'state')
        self.patch_data.start(); self.patch_state.start()
        self.a = self.make_profile('a', ACCOUNT_A, ORG_A)
        self.b = self.make_profile('b', ACCOUNT_B, ORG_B)
        self.stopped = mock.patch.object(m, 'active_profiles', return_value={})
        self.stopped.start()

    def tearDown(self):
        self.stopped.stop(); self.patch_state.stop(); self.patch_data.stop()
        self.tmp.cleanup()

    def make_profile(self, key, account, org):
        root = m.DATA[key]
        folder = root / 'claude-code-sessions' / account / org
        folder.mkdir(parents=True)
        if key != 'a':
            (root / '.local-claude-profile').write_text('1')
        (root / 'config.json').write_text(json.dumps({'lastKnownAccountUuid': account, 'oauth:tokenCache': 'DO-NOT-COPY'}))
        return folder

    def record(self, folder, uid=SESSION_1, title='One', connector='private-a', extra=None):
        record = {'sessionId': 'local_' + uid, 'cliSessionId': uid, 'cwd': '/tmp/project',
                  'title': title, 'remoteMcpServersConfig': [{'id': connector}],
                  'enabledMcpTools': {connector + ':tool': True}, 'remoteControlAutoEligible': True}
        if extra: record.update(extra)
        path = folder / ('local_' + uid + '.json')
        path.write_text(json.dumps(record))
        return path

    def read(self, folder, uid=SESSION_1):
        return json.loads((folder / ('local_' + uid + '.json')).read_text())

    def sync(self, source='a'):
        return m.sync(source, both_stopped=True)

    def test_initial_union_keeps_logins_and_omits_other_accounts_connector(self):
        self.record(self.a, title='From A')
        self.record(self.b, uid=SESSION_2, title='From B', connector='private-b')
        result = self.sync()
        self.assertEqual(result['copied'], 2)
        self.assertEqual(self.read(self.b)['title'], 'From A')
        self.assertEqual(self.read(self.a, SESSION_2)['title'], 'From B')
        self.assertEqual(self.read(self.b)['remoteMcpServersConfig'], [])
        self.assertEqual(self.read(self.b)['enabledMcpTools'], {})
        self.assertEqual(self.read(self.a, SESSION_2)['remoteMcpServersConfig'], [])
        self.assertIn('DO-NOT-COPY', (m.DATA['a'] / 'config.json').read_text())
        self.assertEqual(sorted(p.name for p in self.b.iterdir()), ['local_' + SESSION_1 + '.json', 'local_' + SESSION_2 + '.json'])

    def test_usage_selects_latest_matching_organization_and_reports_staleness(self):
        now = 1_800_000_000
        samples = [
            {'t': (now - 3600) * 1000, 'org': ORG_A, 'u': {'fh': 45, 'sd': 62}},
            {'t': (now - 120) * 1000, 'org': ORG_B, 'u': {'fh': 3, 'sd': 4}},
            {'t': (now + 600) * 1000, 'org': ORG_A, 'u': {'fh': 0, 'sd': 0}},
        ]
        (m.DATA['a'] / 'plan-usage-history.json').write_text(json.dumps({'version':1,'samples':samples}))
        result = m.read_usage(m.DATA['a'], self.a, now=now)
        self.assertEqual(result, {'five_hour':45.0, 'seven_day':62.0, 'observed_at':now-3600, 'stale':True})
        (m.DATA['a'] / 'plan-usage-history.json').write_text(json.dumps({'version':2,'samples':samples}))
        self.assertEqual(m.read_usage(m.DATA['a'], self.a, now=now), result)

    def test_usage_rejects_unknown_malformed_and_out_of_range_values(self):
        now = 1_800_000_000
        file = m.DATA['a'] / 'plan-usage-history.json'
        self.assertIsNone(m.read_usage(m.DATA['a'], self.a, now=now))
        file.write_text('{')
        self.assertIsNone(m.read_usage(m.DATA['a'], self.a, now=now))
        file.write_text(json.dumps({'version':1,'samples':[{'t':now-1,'org':ORG_A,'u':{'fh':True,'sd':101}}]}))
        self.assertIsNone(m.read_usage(m.DATA['a'], self.a, now=now))
        file.write_text(json.dumps({'version':1,'samples':[{'t':now-1,'org':ORG_A,'u':{'fh':0,'sd':-3}}]}))
        result = m.read_usage(m.DATA['a'], self.a, now=now)
        self.assertEqual(result['five_hour'], 0.0)
        self.assertIsNone(result['seven_day'])
        self.assertFalse(result['stale'])
        self.assertIsNone(m.read_usage(m.DATA['a'], None, now=now))
        file.write_text(json.dumps({'version':True,'samples':[{'t':now-1,'org':ORG_A,'u':{'fh':1}}]}))
        self.assertIsNone(m.read_usage(m.DATA['a'], self.a, now=now))
        file.write_text(json.dumps({'version':3,'samples':[{'t':now-1,'org':ORG_A,'u':{'fh':1}}]}))
        self.assertIsNone(m.read_usage(m.DATA['a'], self.a, now=now))
        file.write_text(json.dumps({'version':2,'samples':[{'t':10**500,'org':ORG_A,'u':{'fh':1}}]}))
        self.assertIsNone(m.read_usage(m.DATA['a'], self.a, now=now))
        file.write_text(json.dumps({'version':2,'samples':[{'t':now-1,'org':ORG_A,'u':{'fh':10**500}}]}))
        self.assertIsNone(m.read_usage(m.DATA['a'], self.a, now=now))

    def test_usage_is_not_attributed_when_profile_contains_multiple_accounts(self):
        now = 1_800_000_000
        file = m.DATA['a'] / 'plan-usage-history.json'
        file.write_text(json.dumps({'version':2,'samples':[{'t':now-1,'org':ORG_A,'u':{'fh':1}}]}))
        self.assertIsNotNone(m.read_usage(m.DATA['a'], self.a, now=now))
        (m.DATA['a'] / 'claude-code-sessions' / ACCOUNT_B / ORG_A).mkdir(parents=True)
        self.assertIsNone(m.read_usage(m.DATA['a'], self.a, now=now))

    def test_existing_desktop_signin_can_refresh_without_a_cli_login(self):
        fake = Path(self.tmp.name) / 'fake-usage-probe'
        fake.write_text('''#!/usr/bin/python3
import json, sys
assert sys.argv[1:] == ['--desktop-usage-probe']
request = json.loads(sys.stdin.read())
assert request['account'] == ''' + repr(ACCOUNT_A) + ''' and request['organization'] == ''' + repr(ORG_A) + '''
assert request['allow_prompt'] is True
print(json.dumps({'ok':True, 'usage':{'observed_at':1800000000, 'five_hour':42,
  'seven_day':19, 'five_hour_reset_at':1800003600, 'not_for_storage':'DO-NOT-STORE'}}))
''')
        fake.chmod(0o700)
        with mock.patch.object(m, 'USAGE_PROBE', fake):
            self.assertFalse(m.refresh_usage('a', now=1_800_000_000)['refreshed'])
            self.assertTrue(m.refresh_usage('a', allow_prompt=True, now=1_800_000_000)['refreshed'])
            self.assertFalse(m.refresh_usage('a', allow_prompt=True, now=1_800_000_010)['refreshed'])
        result = m.read_desktop_usage('a', m.DATA['a'], self.a, now=1_800_000_001)
        self.assertEqual((result['five_hour'], result['seven_day']), (42, 19))
        self.assertEqual(result['five_hour_reset_at'], 1_800_003_600)
        self.assertIsNone(m.read_desktop_usage('b', m.DATA['b'], self.b, now=1_800_000_001))
        self.assertTrue(m.usage_config()['enabled'])
        self.assertNotIn('DO-NOT-STORE', (m.STATE / 'usage-state.json').read_text())

    def test_denied_keychain_access_does_not_enable_automatic_usage_checks(self):
        response = json.dumps({'ok':False, 'error_code':'usage_keychain'})
        with mock.patch.object(m.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout=response)) as run:
            with self.assertRaises(m.Problem):
                m.refresh_usage('a', allow_prompt=True, now=1000)
            self.assertFalse(m.usage_config()['enabled'])
            m.usage_tick(now=2000)
            self.assertEqual(run.call_count, 1)

    def test_usage_rate_limit_is_backed_off_and_does_not_reveal_response(self):
        response = json.dumps({'ok':False, 'error_code':'usage_limited', 'retry_seconds':0,
                               'private':'DO-NOT-STORE'})
        with mock.patch.object(m.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout=response)) as run:
            with self.assertRaises(m.Problem):
                m.refresh_usage('a', allow_prompt=True, now=1000)
            with self.assertRaises(m.Problem):
                m.refresh_usage('a', allow_prompt=True, now=1001)
            self.assertEqual(run.call_count, 1)
            with self.assertRaises(m.Problem):
                m.refresh_usage('a', allow_prompt=True, now=1900)
        record = m.usage_config()['profiles']['a']
        self.assertEqual(record['retry_at'], 3700)
        self.assertNotIn('DO-NOT-STORE', (m.STATE / 'usage-state.json').read_text())

    def test_usage_result_is_discarded_if_desktop_account_changes(self):
        response = json.dumps({'ok':True, 'usage':{'observed_at':1000, 'five_hour':42}})
        with mock.patch.object(m, 'session_dir', side_effect=[self.a, self.b]), \
             mock.patch.object(m.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout=response)):
            with self.assertRaises(m.Problem):
                m.refresh_usage('a', allow_prompt=True, now=1000)
        self.assertFalse(m.usage_config()['enabled'])
        self.assertNotIn('usage', m.usage_config()['profiles']['a'])

    def test_usage_poll_runs_one_due_profile_without_a_keychain_prompt(self):
        m.save_state('usage-state.json', {'version':1, 'enabled':True, 'profiles':{
            'a':{'profile':m.profile_fingerprint(ACCOUNT_A, ORG_A), 'attempt_at':1000, 'retry_at':1300},
            'b':{'profile':m.profile_fingerprint(ACCOUNT_B, ORG_B), 'attempt_at':1000, 'retry_at':1300}}})
        with mock.patch.object(m, 'refresh_usage') as refresh:
            m.usage_tick(now=1299)
            refresh.assert_not_called()
            m.usage_tick(now=1300)
            refresh.assert_called_once_with('a', allow_prompt=False, now=1300)

    def test_status_keeps_api_resets_with_a_newer_desktop_percentage(self):
        now = 1_800_000_000
        m.save_state('usage-state.json', {'version':1, 'enabled':True, 'profiles':{
            'a':{'profile':m.profile_fingerprint(ACCOUNT_A, ORG_A), 'usage':{
                'observed_at':now - 60, 'five_hour':40, 'seven_day':19,
                'five_hour_reset_at':now + 3600, 'seven_day_reset_at':now + 86400}}}})
        sample = {'five_hour':42, 'seven_day':20, 'observed_at':now - 10, 'stale':False}
        with mock.patch.object(m.time, 'time', return_value=now), \
             mock.patch.object(m, 'processes', return_value=[]), \
             mock.patch.object(m, 'read_usage', side_effect=[sample, None]):
            result = m.status()['profiles'][0]['usage']
        self.assertEqual(result['five_hour'], 42)
        self.assertEqual(result['five_hour_reset_at'], now + 3600)
        self.assertEqual(result['seven_day_reset_at'], now + 86400)

    def test_status_does_not_restore_an_old_percentage_after_reset(self):
        now = 1_800_000_000
        m.save_state('usage-state.json', {'version':1, 'enabled':True, 'profiles':{
            'a':{'profile':m.profile_fingerprint(ACCOUNT_A, ORG_A), 'usage':{
                'observed_at':now - 60, 'five_hour':100, 'five_hour_reset_at':now - 5}}}})
        sample = {'five_hour':100, 'seven_day':None, 'observed_at':now - 10, 'stale':False}
        with mock.patch.object(m.time, 'time', return_value=now), \
             mock.patch.object(m, 'processes', return_value=[]), \
             mock.patch.object(m, 'read_usage', side_effect=[sample, None]):
            result = m.status()['profiles'][0]['usage']
        self.assertIsNone(result['five_hour'])
        self.assertEqual(result['five_hour_reset_at'], now - 5)

    def test_saved_usage_hides_windows_after_their_reset(self):
        usage = {'observed_at':1000, 'five_hour':80, 'seven_day':20,
                 'five_hour_reset_at':1100, 'seven_day_reset_at':2000}
        result = m.saved_usage(usage, now=1101)
        self.assertIsNone(result['five_hour'])
        self.assertEqual(result['seven_day'], 20)

    def test_refresh_does_not_restore_an_expired_window_when_another_is_valid(self):
        payload = {'ok':True, 'usage':{'observed_at':1000, 'five_hour':80, 'seven_day':20,
                                       'five_hour_reset_at':999, 'seven_day_reset_at':2000}}
        with mock.patch.object(m.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout=json.dumps(payload))):
            m.refresh_usage('a', allow_prompt=True, now=1000)
        result = m.read_desktop_usage('a', m.DATA['a'], self.a, now=1001)
        self.assertIsNone(result['five_hour'])
        self.assertEqual(result['seven_day'], 20)

    def test_desktop_warmup_defaults_off_and_ignores_legacy_login_schedule(self):
        m.save_state('warmup.json', {'version':1, 'profiles':{'a':{'enabled':True}}})
        self.assertFalse(m.warmup_public()['a']['enabled'])

    def test_desktop_warmup_schedule_fires_once_without_a_cli_login(self):
        morning = datetime.datetime(2026, 10, 29, 8, 0).astimezone()
        due = morning.replace(hour=9)
        m.warmup_save('a', True, 9, 0, now=morning)
        response = json.dumps({'ok':True, 'sent':True, 'private':'DO-NOT-STORE'})
        with mock.patch.object(m.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout=response)) as run:
            self.assertFalse(m.warmup_execute('a', scheduled=True, now=due - datetime.timedelta(seconds=1))['sent'])
            self.assertTrue(m.warmup_execute('a', scheduled=True, now=due)['sent'])
            self.assertFalse(m.warmup_execute('a', scheduled=True, now=due + datetime.timedelta(seconds=20))['sent'])
            self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], [str(m.USAGE_PROBE), '--desktop-warmup-probe'])
        request = json.loads(run.call_args.kwargs['input'])
        self.assertEqual(request, {'profile':str(m.DATA['a']), 'account':ACCOUNT_A,
                                   'organization':ORG_A, 'allow_prompt':False})
        self.assertNotIn('DO-NOT-STORE', (m.STATE / 'desktop-warmup.json').read_text())

    def test_manual_warmup_works_with_scheduling_off_and_blocks_double_clicks(self):
        now = datetime.datetime(2026, 10, 29, 8, 0).astimezone()
        response = json.dumps({'ok':True, 'sent':True})
        with mock.patch.object(m.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout=response)) as run:
            self.assertTrue(m.warmup_execute('a', allow_prompt=True, now=now)['sent'])
            with self.assertRaises(m.WarmupProblem) as error:
                m.warmup_execute('a', allow_prompt=True, now=now + datetime.timedelta(seconds=30))
        self.assertEqual(error.exception.code, 'warm_error_busy')
        self.assertEqual(run.call_count, 1)
        self.assertTrue(json.loads(run.call_args.kwargs['input'])['allow_prompt'])
        self.assertFalse(m.warmup_public(now)['a']['enabled'])

    def test_missed_desktop_warmup_does_not_send_late(self):
        now = datetime.datetime(2026, 10, 29, 8, 0).astimezone()
        m.warmup_save('a', True, 9, 0, now=now)
        with mock.patch.object(m.subprocess, 'Popen') as spawn:
            m.schedule_warmup_tick(now=now.replace(hour=10))
            spawn.assert_not_called()
        self.assertEqual(m.warmup_public(now)['a']['last_status'], 'missed')

    def test_scheduler_spawns_a_silent_worker_only_when_due(self):
        now = datetime.datetime(2026, 10, 29, 8, 0).astimezone()
        m.warmup_save('a', True, 9, 15, now=now)
        with mock.patch.object(m.subprocess, 'Popen') as spawn:
            m.schedule_warmup_tick(now=now.replace(hour=9, minute=14))
            spawn.assert_not_called()
            m.schedule_warmup_tick(now=now.replace(hour=9, minute=15))
        self.assertEqual(spawn.call_count, 1)
        self.assertEqual(spawn.call_args.args[0][-3:], ['warmup-run', 'a', '--scheduled'])

    def test_failed_scheduled_warmup_is_not_retried_that_day(self):
        now = datetime.datetime(2026, 10, 29, 8, 0).astimezone()
        m.warmup_save('a', True, 9, 0, now=now)
        response = json.dumps({'ok':False, 'error_code':'usage_expired', 'private':'DO-NOT-STORE'})
        with mock.patch.object(m.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout=response)) as run:
            with self.assertRaises(m.WarmupProblem) as error:
                m.warmup_execute('a', scheduled=True, now=now.replace(hour=9))
            self.assertEqual(error.exception.code, 'usage_expired')
            self.assertFalse(m.warmup_execute('a', scheduled=True, now=now.replace(hour=9, second=30))['sent'])
        self.assertEqual(run.call_count, 1)
        self.assertNotIn('DO-NOT-STORE', (m.STATE / 'desktop-warmup.json').read_text())

    def test_known_exhausted_quota_does_not_send_a_warmup_message(self):
        now = datetime.datetime(2026, 10, 29, 8, 0).astimezone()
        m.save_state('usage-state.json', {'version':1, 'enabled':True, 'profiles':{'a':{
            'profile':m.profile_fingerprint(ACCOUNT_A, ORG_A),
            'usage':{'observed_at':now.timestamp(), 'five_hour':100}}}})
        with mock.patch.object(m.subprocess, 'run') as run:
            with self.assertRaises(m.WarmupProblem) as error:
                m.warmup_execute('a', allow_prompt=True, now=now)
            run.assert_not_called()
        self.assertEqual(error.exception.code, 'warm_error_limited')

    def test_warmup_does_not_follow_a_different_desktop_login(self):
        now = datetime.datetime(2026, 10, 29, 8, 0).astimezone()
        m.warmup_save('a', True, 9, 0, now=now)
        with mock.patch.object(m, 'account_id', return_value=ACCOUNT_B), \
             mock.patch.object(m, 'session_dir', return_value=self.b), \
             mock.patch.object(m.subprocess, 'Popen') as spawn:
            m.schedule_warmup_tick(now=now.replace(hour=9))
            spawn.assert_not_called()
            self.assertFalse(m.warmup_public(now)['a']['enabled'])

    def test_past_warmup_time_starts_tomorrow_and_can_be_disabled(self):
        now = datetime.datetime(2026, 10, 29, 10, 0).astimezone()
        m.warmup_save('a', True, 9, 0, now=now)
        self.assertIsNone(m.warmup_decision(m.warmup_config()['profiles']['a'], now))
        expected = (now + datetime.timedelta(days=1)).replace(hour=9).timestamp()
        self.assertEqual(m.warmup_public(now)['a']['next_at'], expected)
        m.warmup_save('a', False, 9, 0, now=now)
        self.assertFalse(m.warmup_public(now)['a']['enabled'])

    def test_three_profiles_converge_and_subsequent_updates_propagate(self):
        m.DATA['c'] = Path(self.tmp.name) / 'c'
        c = self.make_profile('c', ACCOUNT_C, ORG_C)
        self.record(self.a, title='A')
        self.record(self.b, uid=SESSION_2, title='B')
        self.record(c, uid=SESSION_3, title='C')
        result = self.sync('b')
        self.assertEqual(result['conflicts'], 0)
        for folder in (self.a, self.b, c):
            self.assertEqual({self.read(folder, sid)['title'] for sid in (SESSION_1, SESSION_2, SESSION_3)}, {'A','B','C'})
        self.record(self.a, title='Updated A')
        self.stopped.stop()
        try:
            with mock.patch.object(m, 'active_profiles', return_value={123:'a'}):
                result = m.sync('a')
                self.assertEqual(result['conflicts'], 0)
        finally:
            self.stopped.start()
        self.assertEqual(self.read(self.b)['title'], 'Updated A')
        self.assertEqual(self.read(c)['title'], 'Updated A')

    def test_scratch_workspace_keeps_stable_path_but_other_profile_paths_are_skipped(self):
        scratch = m.DATA['b'] / 'scratch-workspaces' / 'account' / 'session'
        scratch.mkdir(parents=True)
        self.record(self.b, extra={'cwd': str(scratch), 'originCwd': str(scratch)})
        result = self.sync('b')
        self.assertEqual(result['copied'], 1)
        self.assertEqual(self.read(self.a)['cwd'], str(scratch))
        self.assertFalse(m.safe_session({'cwd':str(m.DATA['b'] / 'config.json')}))
        outside = Path(self.tmp.name) / 'outside'
        outside.mkdir()
        (scratch / 'outside-link').symlink_to(outside, target_is_directory=True)
        self.assertFalse(m.safe_session({'cwd':str(scratch / 'outside-link')}))

    def test_upgrading_preserves_existing_two_account_baseline(self):
        old = self.record(self.a, title='Old')
        self.record(self.b, title='Old', connector='private-b')
        old_record, _ = m.parse_record(old)
        fingerprint = m.hashlib.sha256((str(self.a) + '\n' + str(self.b)).encode()).hexdigest()
        m.save_state('sync-state.json', {'pair':fingerprint, 'baseline':{old.name:m.digest(m.portable(old_record))}})
        self.record(self.b, title='New B', connector='private-b')
        self.stopped.stop()
        try:
            with mock.patch.object(m, 'active_profiles', return_value={123:'b'}):
                result = m.sync('b')
        finally:
            self.stopped.start()
        self.assertEqual(result['conflicts'], 0)
        self.assertEqual(self.read(self.a)['title'], 'New B')

    def test_changed_source_updates_unchanged_target_and_keeps_target_private_fields(self):
        self.record(self.a)
        self.sync()
        target = self.b / ('local_' + SESSION_1 + '.json')
        data = json.loads(target.read_text())
        data['remoteMcpServersConfig'] = [{'id': 'private-b'}]
        target.write_text(json.dumps(data))
        self.record(self.a, title='Updated')
        result = self.sync('a')
        self.assertEqual(result['copied'], 1)
        self.assertEqual(self.read(self.b)['title'], 'Updated')
        self.assertEqual(self.read(self.b)['remoteMcpServersConfig'], [{'id': 'private-b'}])
        self.assertTrue(list((m.STATE / 'backups').glob('*.bak')))
        self.assertEqual((m.STATE / 'backups').stat().st_mode & 0o777, 0o700)

    def test_both_changed_is_conflict_and_keeps_both(self):
        self.record(self.a)
        self.sync()
        self.record(self.a, title='Change A')
        self.record(self.b, title='Change B', connector='private-b')
        result = self.sync('a')
        self.assertGreater(result['conflicts'], 0)
        self.assertEqual(self.read(self.a)['title'], 'Change A')
        self.assertEqual(self.read(self.b)['title'], 'Change B')

    def test_reverse_pass_carries_parked_change_without_false_conflict(self):
        self.record(self.a)
        self.sync()
        self.record(self.a, title='Updated while A was active')
        result = self.sync('b')
        self.assertEqual(result['conflicts'], 0)
        self.assertEqual(self.read(self.b)['title'], 'Updated while A was active')

    def test_different_existing_records_do_not_overwrite_without_baseline(self):
        self.record(self.a, title='A'); self.record(self.b, title='B')
        self.assertGreater(self.sync()['conflicts'], 0)
        self.assertEqual(self.read(self.a)['title'], 'A')
        self.assertEqual(self.read(self.b)['title'], 'B')

    def test_deleted_marker_does_not_resurrect_or_delete_other_copy(self):
        self.record(self.a)
        (self.b / ('deleted_' + SESSION_1)).write_text('1')
        result = self.sync()
        self.assertFalse((self.b / ('local_' + SESSION_1 + '.json')).exists())
        self.assertTrue((self.a / ('local_' + SESSION_1 + '.json')).exists())
        self.assertGreater(result['skipped'], 0)

    def test_malformed_unsafe_and_symlink_records_are_skipped(self):
        self.record(self.a, extra={'startedFromEnvironmentId': 'special'})
        (self.a / ('local_' + SESSION_2 + '.json')).write_text('{')
        result = self.sync()
        self.assertGreaterEqual(result['skipped'], 2)
        self.assertEqual(list(self.b.iterdir()), [])
        real = self.record(self.a)
        symlink = self.b / real.name
        symlink.symlink_to(real)
        result = self.sync()
        self.assertTrue(symlink.is_symlink())
        self.assertGreater(result['skipped'], 0)

    def test_multiple_orgs_never_guessed(self):
        extra = self.a.parent / 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee'
        extra.mkdir()
        with self.assertRaises(m.Problem):
            m.session_dir(m.DATA['a'])

    def test_same_account_in_both_profiles_does_not_sync(self):
        root_b = m.DATA['b']
        (root_b / 'config.json').write_text(json.dumps({'lastKnownAccountUuid': ACCOUNT_A}))
        same = root_b / 'claude-code-sessions' / ACCOUNT_A / ORG_B
        same.mkdir(parents=True)
        self.record(self.a)
        with self.assertRaises(m.Problem):
            self.sync()
        self.assertEqual(list(same.iterdir()), [])

    def test_running_profile_is_never_written(self):
        self.record(self.a)
        self.stopped.stop()
        try:
            with mock.patch.object(m, 'active_profiles', return_value={123: 'a'}):
                result = m.sync('a')
                self.assertEqual(result['copied'], 1)
                self.record(self.b, uid=SESSION_2, title='B only')
                m.sync('a')
                self.assertFalse((self.a / ('local_' + SESSION_2 + '.json')).exists())
        finally:
            self.stopped.start()

    def test_guard_stops_if_another_claude_starts(self):
        self.record(self.a)
        self.stopped.stop()
        try:
            with mock.patch.object(m, 'active_profiles', return_value={123:'a',456:'b'}):
                with self.assertRaises(m.Stopped):
                    m.sync('a')
                self.assertFalse((self.b / ('local_' + SESSION_1 + '.json')).exists())
        finally:
            self.stopped.start()

    def test_process_detection_identifies_default_custom_and_unknown(self):
        a = (1, 0, m.APP_BIN)
        b = (2, 0, m.APP_BIN + ' --user-data-dir=' + str(m.DATA['b']))
        unknown = (3, 0, m.APP_BIN + ' --user-data-dir=/tmp/other')
        b_with_args = (4, 0, m.APP_BIN + ' --user-data-dir=' + str(m.DATA['b']) + ' --flag')
        b_quoted = (5, 0, m.APP_BIN + ' --user-data-dir="' + str(m.DATA['b']) + '" --flag')
        impostor = (6, 0, m.APP_BIN + ' --user-data-dir=' + str(m.DATA['b']) + '-other')
        self.stopped.stop()
        try:
            self.assertEqual(m.active_profiles([a, b, unknown, b_with_args, b_quoted, impostor]),
                             {1:'a', 2:'b', 3:'unknown', 4:'b', 5:'b', 6:'unknown'})
        finally:
            self.stopped.start()

    def test_switch_reconciles_both_sides_after_graceful_quit(self):
        self.record(self.a, title='A session')
        self.record(self.b, uid=SESSION_2, title='B session', connector='private-b')
        self.stopped.stop()
        running = {42: 'a'}
        try:
            with mock.patch.object(m, 'active_profiles', side_effect=lambda: dict(running)), \
                 mock.patch.object(m.os, 'kill', side_effect=lambda pid, sig: running.clear()) as kill, \
                 mock.patch.object(m.subprocess, 'run') as launch:
                result = m.switch('b', allow_quit=True)
            self.assertTrue(result['sync']['ready'])
            self.assertEqual(result['sync']['copied'], 2)
            self.assertEqual(self.read(self.b)['title'], 'A session')
            self.assertEqual(self.read(self.a, SESSION_2)['title'], 'B session')
            kill.assert_called_once_with(42, m.signal.SIGTERM)
            self.assertIn('--user-data-dir=' + str(m.DATA['b']), launch.call_args.args[0])
        finally:
            self.stopped.start()

    def test_switch_refuses_to_quit_without_explicit_confirmation(self):
        self.stopped.stop()
        try:
            with mock.patch.object(m, 'active_profiles', return_value={42:'a'}), \
                 mock.patch.object(m.os, 'kill') as kill:
                with self.assertRaises(m.Problem):
                    m.switch('b', allow_quit=False)
                kill.assert_not_called()
        finally:
            self.stopped.start()

    def test_switch_refuses_multiple_or_unknown_profiles(self):
        self.stopped.stop()
        try:
            for active in ({42:'a', 43:'b'}, {42:'unknown'}):
                with mock.patch.object(m, 'active_profiles', return_value=active), \
                     mock.patch.object(m.os, 'kill') as kill:
                    with self.assertRaises(m.Problem):
                        m.switch('b', allow_quit=True)
                    kill.assert_not_called()
        finally:
            self.stopped.start()

    def test_profile_discovery_and_add_reuses_uninitialized_slot(self):
        root = Path(self.tmp.name) / 'support'
        root.mkdir()
        with mock.patch.object(m, 'SUPPORT', root):
            self.assertEqual(list(m.discover_profiles()), ['a', 'b'])
            result = m.add_profile()
            self.assertEqual(result['target'], 'b')
            self.assertTrue((root / 'Claude Local B').is_dir())
            self.assertEqual(m.add_profile()['target'], 'b')
            (root / 'Claude Local B' / 'config.json').write_text('{}')
            self.assertEqual(m.add_profile()['target'], 'c')
            self.assertEqual(list(m.discover_profiles()), ['a', 'b', 'c'])

    def test_new_account_does_not_adopt_unrelated_existing_directory(self):
        root = Path(self.tmp.name) / 'support'
        (root / 'Claude Local B').mkdir(parents=True)
        (root / 'Claude Local B' / '.local-claude-profile').write_text('1')
        (root / 'Claude Local B' / 'config.json').write_text('{}')
        (root / 'Claude Local C').mkdir()
        with mock.patch.object(m, 'SUPPORT', root):
            self.assertEqual(list(m.discover_profiles()), ['a', 'b'])
            self.assertEqual(m.add_profile()['target'], 'd')
            self.assertEqual(list(m.discover_profiles()), ['a', 'b', 'd'])
            self.assertFalse((root / 'Claude Local C' / '.local-claude-profile').exists())

    def test_unrelated_preexisting_b_directory_is_not_adopted(self):
        root = Path(self.tmp.name) / 'support'
        (root / 'Claude Local B').mkdir(parents=True)
        with mock.patch.object(m, 'SUPPORT', root):
            self.assertEqual(list(m.discover_profiles()), ['a'])
            self.assertEqual(m.add_profile()['target'], 'c')
            self.assertFalse((root / 'Claude Local B' / '.local-claude-profile').exists())

    def test_failed_sync_reopens_previous_profile(self):
        self.stopped.stop()
        running = {42: 'a'}
        try:
            with mock.patch.object(m, 'active_profiles', side_effect=lambda: dict(running)), \
                 mock.patch.object(m.os, 'kill', side_effect=lambda pid, sig: running.clear()), \
                 mock.patch.object(m, 'sync', side_effect=m.Problem('cannot sync')), \
                 mock.patch.object(m, 'launch_profile') as launch:
                with self.assertRaises(m.Problem):
                    m.switch('b', allow_quit=True)
                launch.assert_called_once_with('a')
        finally:
            self.stopped.start()

    def test_seven_locales_have_identical_ui_keys(self):
        translations = json.loads((Path(__file__).resolve().parents[1] / 'assets/translations.json').read_text())
        self.assertEqual(set(translations), {'en', 'zh', 'ja', 'ko', 'es', 'fr', 'de'})
        keys = set(translations['en'])
        for locale, values in translations.items():
            self.assertEqual(set(values), keys, locale)
            self.assertEqual(values['current'].count('%@'), 1, locale)
            self.assertEqual(values['usage_updated'].count('%@'), 1, locale)
            self.assertEqual(values['usage_stale'].count('%@'), 1, locale)
            for key in ('usage_resets_at', 'usage_reset_pending'):
                self.assertEqual(values[key].count('%@'), 1, (locale, key))


if __name__ == '__main__':
    unittest.main()
