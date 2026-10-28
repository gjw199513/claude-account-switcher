import importlib.util
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


if __name__ == '__main__':
    unittest.main()
