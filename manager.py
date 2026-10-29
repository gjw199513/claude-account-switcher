#!/usr/bin/env python3
"""Local Claude Desktop profiles and conservative Code-session reconciliation.

This uses macOS, Python's standard library, and the existing Claude installation.
Session reconciliation never moves credentials. The optional Desktop usage
probe separately uses a token in memory with explicit Keychain authorization.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterator

HOME = Path.home()
APP = Path('/Applications/Claude.app')
APP_BIN = str(APP / 'Contents/MacOS/Claude')
SUPPORT = HOME / 'Library/Application Support'
DATA = {'a': SUPPORT / 'Claude', 'b': SUPPORT / 'Claude Local B'}
STATE = SUPPORT / 'Local Claude Accounts'
USAGE_PROBE = HOME / 'Applications/Claude Account Switcher.app/Contents/MacOS/LocalClaudeAccounts'
MAX_RECORD = 8 * 1024 * 1024
UUID = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
FILENAME = re.compile(r'^local_(' + UUID + r')\.json$')
UUID_ONLY = re.compile('^' + UUID + '$')
# These fields are specific to a Claude account/organization or remote bridge.
# Preserve the destination's own values; never copy the source's values.
PRIVATE_FIELDS = {
    'remoteMcpServersConfig', 'enabledMcpTools', 'remoteControlAutoEligible',
    'steeredByRemoteClient', 'remoteControl', 'remoteControlSessionId',
    'remoteSessionId', 'remoteSessionUrl', 'bridgeSessionId', 'accountUuid',
    'organizationUuid', 'accountId', 'organizationId', 'emailAddress',
}


class Problem(Exception):
    pass


class Stopped(Problem):
    pass


class WarmupProblem(Problem):
    def __init__(self, code: str):
        super().__init__('预热未完成，请查看账号状态后重试。')
        self.code = code


def discover_profiles() -> dict[str, Path]:
    """Each profile stays in its own directory; no separate account database."""
    result = {'a': SUPPORT / 'Claude'}
    for code in range(ord('b'), ord('z') + 1):
        key = chr(code)
        path = SUPPORT / ('Claude Local ' + key.upper())
        marker = path / '.local-claude-profile'
        empty_b_slot = key == 'b' and not path.exists() and not path.is_symlink()
        if empty_b_slot or (not path.is_symlink() and marker.is_file() and not marker.is_symlink()):
            result[key] = path
    return result


def private_dir(path: Path) -> None:
    if path.is_symlink():
        raise Problem('本地工具目录不能是软链接。')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def ensure_profile(path: Path) -> None:
    marker = path / '.local-claude-profile'
    if path.is_symlink() or marker.is_symlink():
        raise Problem('账号目录或标记不能是软链接。')
    if path.exists():
        if not path.is_dir() or not marker.is_file():
            raise Problem('账号目录已存在且不属于此工具。')
        private_dir(path)
    else:
        path.mkdir(parents=True, mode=0o700, exist_ok=False)
        atomic_write(marker, b'1\n')


@contextlib.contextmanager
def locked() -> Iterator[None]:
    private_dir(STATE)
    fd = os.open(STATE / 'lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Problem('另一个同步或切换正在进行，请稍后再试。') from exc
        yield
    finally:
        os.close(fd)


def read_regular(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_RECORD:
            raise Problem('会话索引不是普通文件或文件过大。')
        with os.fdopen(fd, 'rb', closefd=False) as handle:
            raw = handle.read(MAX_RECORD + 1)
        after = os.fstat(fd)
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise Problem('会话索引正在写入，请稍后重试。')
        if len(raw) > MAX_RECORD:
            raise Problem('会话索引文件过大。')
        return raw
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes, previous: bytes | None = None) -> None:
    if path.is_symlink():
        raise Problem('拒绝覆盖软链接。')
    fd, tmp = tempfile.mkstemp(prefix='.claude-local-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if previous is None:
            # Create without replacing a file another process may have just written.
            os.link(tmp, path, follow_symlinks=False)
            os.unlink(tmp)
        else:
            if read_regular(path) != previous:
                raise Problem('目标会话索引刚刚发生变化，已保留原件。')
            os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save_state(name: str, value: dict[str, Any]) -> None:
    private_dir(STATE)
    path = STATE / name
    prior = read_regular(path) if path.exists() else None
    atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True).encode(), prior)


def load_state(name: str) -> dict[str, Any]:
    try:
        obj = json.loads(read_regular(STATE / name))
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError, Problem):
        return {}


def add_profile() -> dict[str, Any]:
    """Create or reuse one uninitialized profile; actual sign-in remains in Claude."""
    global DATA
    with locked():
        DATA = discover_profiles()
        active = active_profiles()
        for key, path in DATA.items():
            if key != 'a' and key not in active.values() and not (path / 'config.json').exists():
                ensure_profile(path)
                return {'target': key}
        for code in range(ord('b'), ord('z') + 1):
            key = chr(code)
            if key not in DATA:
                path = SUPPORT / ('Claude Local ' + key.upper())
                if path.exists() or path.is_symlink():
                    continue
                ensure_profile(path)
                DATA[key] = path
                return {'target': key}
        raise Problem('最多支持 26 个本机账号。')


def processes() -> list[tuple[int, int, str]]:
    text = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,command='], check=True,
                          capture_output=True, text=True).stdout
    result = []
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            result.append((int(parts[0]), int(parts[1]), parts[2]))
    return result


def active_profiles(rows: list[tuple[int, int, str]] | None = None) -> dict[int, str]:
    found: dict[int, str] = {}
    for pid, _, cmd in rows if rows is not None else processes():
        if not cmd.startswith(APP_BIN):
            continue
        rest = cmd[len(APP_BIN):]
        if rest and not rest.startswith(' '):
            continue
        if '--type=' in rest:
            continue
        if '--user-data-dir=' not in rest:
            found[pid] = 'a'
        else:
            value = rest.split('--user-data-dir=', 1)[1].strip()
            # ps can print arguments after the path. Match the whole known path followed
            # by an argument boundary; paths themselves can contain spaces.
            found[pid] = 'unknown'
            for key, profile in DATA.items():
                expected = str(profile)
                variants = (expected, '"' + expected + '"', "'" + expected + "'")
                if any(value == item or value.startswith(item + ' -') for item in variants):
                    found[pid] = key
                    break
    return found


def child_sessions(pid: int, rows: list[tuple[int, int, str]]) -> int:
    children: dict[int, list[tuple[int, str]]] = {}
    for child, parent, cmd in rows:
        children.setdefault(parent, []).append((child, cmd))
    todo, count, seen = [pid], 0, set()
    while todo:
        parent = todo.pop()
        if parent in seen:
            continue
        seen.add(parent)
        for child, cmd in children.get(parent, []):
            if '/claude-code/' in cmd and '/MacOS/claude' in cmd:
                count += 1
            todo.append(child)
    return count


def account_id(profile: Path) -> str | None:
    if profile.is_symlink():
        raise Problem('Claude 的账号目录是软链接，已暂停同步。')
    config = profile / 'config.json'
    if not config.is_file() or config.is_symlink():
        return None
    try:
        # Do not log or save this file: it also contains credentials.
        with config.open('r', encoding='utf-8') as handle:
            account = json.load(handle).get('lastKnownAccountUuid')
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(account, str) or not UUID_ONLY.fullmatch(account):
        return None
    return account


def session_dir(profile: Path) -> Path | None:
    """Choose only a uniquely identified current account/org directory; never guess."""
    account = account_id(profile)
    if account is None:
        return None
    root = profile / 'claude-code-sessions'
    account_dir = root / account
    if not account_dir.is_dir() or root.is_symlink() or account_dir.is_symlink():
        return None
    candidates = [p for p in account_dir.iterdir() if p.is_dir() and not p.is_symlink()
                  and UUID_ONLY.fullmatch(p.name)]
    if len(candidates) > 1:
        raise Problem('一个账号存在多个组织的会话目录，无法安全确定当前组织，已暂停同步。')
    return candidates[0] if candidates else None


def parse_record(path: Path) -> tuple[dict[str, Any], bytes]:
    match = FILENAME.fullmatch(path.name)
    if not match:
        raise Problem('会话文件名不符合预期。')
    raw = read_regular(path)
    try:
        record = json.loads(raw)
    except ValueError as exc:
        raise Problem('会话索引不是有效 JSON，已保留原件。') from exc
    if (not isinstance(record, dict) or record.get('sessionId') != path.stem
            or not isinstance(record.get('cliSessionId'), str)
            or not isinstance(record.get('cwd'), str)):
        raise Problem('会话索引结构不符合预期，已保留原件。')
    return record, raw


def is_private(key: str) -> bool:
    lower = key.lower()
    return (key in PRIVATE_FIELDS or any(s in lower for s in
            ('token', 'oauth', 'account', 'organization', 'authorization', 'apikey', 'password', 'cookie'))
            or lower in ('userid', 'useremail', 'email')
            or lower.startswith('remotecontrol') or lower.startswith('bridgesession'))


def portable(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if not is_private(k)}


def digest(obj: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def safe_session(record: dict[str, Any]) -> bool:
    # Remote, profile-private and worktree sessions need extra account-specific metadata.
    for k, v in record.items():
        low = k.lower()
        if v and (low.startswith('sshremote') or low.startswith('wsl')
                  or low in ('startedfromenvironmentid', 'remoteenvironmentid')):
            return False
    for k in ('cwd', 'originCwd'):
        value = record.get(k)
        if not isinstance(value, str):
            continue
        if '/.claude/worktrees/' in value:
            return False
        path = Path(value)
        for profile in DATA.values():
            try:
                relative = path.relative_to(profile)
            except ValueError:
                continue
            # Scratch folders have stable absolute paths because profiles are never
            # moved. Permit only real, existing folders inside the scratch root.
            if not relative.parts or relative.parts[0] != 'scratch-workspaces':
                return False
            scratch = profile / 'scratch-workspaces'
            if not path.is_dir() or not scratch.is_dir() or scratch.is_symlink():
                return False
            try:
                path.resolve(strict=True).relative_to(scratch.resolve(strict=True))
            except (ValueError, OSError):
                return False
    return True


def assembled(source: dict[str, Any], destination: dict[str, Any] | None) -> dict[str, Any]:
    result = portable(source)
    if destination is None:
        # A connector UUID belongs to an org; re-enable connectors explicitly within that account.
        if 'remoteMcpServersConfig' in source:
            result['remoteMcpServersConfig'] = []
        if 'enabledMcpTools' in source:
            result['enabledMcpTools'] = {} if isinstance(source['enabledMcpTools'], dict) else []
        if 'remoteControlAutoEligible' in source:
            result['remoteControlAutoEligible'] = False
        if 'steeredByRemoteClient' in source:
            result['steeredByRemoteClient'] = False
    else:
        result.update({k: v for k, v in destination.items() if is_private(k)})
    return result


def backup(raw: bytes, name: str) -> None:
    root = STATE / 'backups'
    private_dir(root)
    # Content-addressed backups avoid duplicating an unchanged previous version forever.
    suffix = hashlib.sha256(raw).hexdigest()[:16]
    target = root / (name + '.' + suffix + '.bak')
    if not target.exists():
        try:
            atomic_write(target, raw)
        except FileExistsError:
            pass


def reconcile(source: Path, target: Path, baseline: dict[str, str],
              guard: Callable[[], None] = lambda: None) -> tuple[int, int, int]:
    copied = conflicts = skipped = 0
    if source.is_symlink() or target.is_symlink() or not source.is_dir() or not target.is_dir():
        raise Problem('会话目录不可用或是软链接，已暂停同步。')
    for item in sorted(source.iterdir()):
        match = FILENAME.fullmatch(item.name)
        if not match:
            continue
        target_item = target / item.name
        # A deletion marker is deliberately not treated as a request to delete the other copy.
        if (source / ('deleted_' + match.group(1))).exists() or (target / ('deleted_' + match.group(1))).exists():
            skipped += 1
            continue
        try:
            src, _ = parse_record(item)
            if not safe_session(src):
                skipped += 1
                continue
            src_hash = digest(portable(src))
            dst = None
            old = None
            if target_item.exists() or target_item.is_symlink():
                dst, old = parse_record(target_item)
                if not safe_session(dst):
                    skipped += 1
                    continue
                dst_hash = digest(portable(dst))
                if src_hash == dst_hash:
                    baseline[item.name] = src_hash
                    continue
                known = baseline.get(item.name)
                # Only overwrite a known, unchanged destination with a changed source.
                if known and src_hash == known and dst_hash != known:
                    # The other side changed; a reverse pass can safely carry it back.
                    continue
                if not known or dst_hash != known or src_hash == known:
                    conflicts += 1
                    continue
            new = json.dumps(assembled(src, dst), ensure_ascii=False, indent=2).encode() + b'\n'
            if old is not None:
                backup(old, item.name)
            guard()
            atomic_write(target_item, new, old)
            baseline[item.name] = src_hash
            copied += 1
        except Stopped:
            raise
        except (OSError, ValueError, Problem):
            skipped += 1
    return copied, conflicts, skipped


def sync(source_key: str | None, both_stopped: bool = False) -> dict[str, Any]:
    discovered = {k: session_dir(v) for k, v in DATA.items()}
    paths = {k: p for k, p in discovered.items() if p is not None}
    if len(paths) < 2:
        return {'ready': False, 'copied': 0, 'conflicts': 0, 'skipped': 0}
    accounts = [p.parent.name.lower() for p in paths.values()]
    if len(accounts) != len(set(accounts)):
        raise Problem('多个窗口使用了同一个 Claude 账号，请登录不同账号。')
    saved = load_state('sync-state.json')
    pairs: dict[str, dict[str, str]] = saved.get('pairs', {})
    if not isinstance(pairs, dict):
        pairs = {}

    def pair_key(a: Path, b: Path) -> str:
        values = sorted((str(a), str(b)))
        return hashlib.sha256(('\n'.join(values)).encode()).hexdigest()

    # Preserve baselines created by the original two-profile version.
    if 'a' in paths and 'b' in paths:
        a, b = paths['a'], paths['b']
        legacy = hashlib.sha256((str(a) + '\n' + str(b)).encode()).hexdigest()
        if saved.get('pair') == legacy and isinstance(saved.get('baseline'), dict):
            pairs.setdefault(pair_key(a, b), saved['baseline'])

    total = [0, 0, 0]
    hub = source_key if source_key in paths else next(iter(paths))
    if both_stopped:
        others = [k for k in paths if k != hub]
        order = [(k, hub) for k in others] + [(hub, k) for k in others]
    elif source_key in paths:
        order = [(hub, k) for k in paths if k != hub]
    else:
        raise Problem('Claude 运行状态不明确，已暂停同步。')

    def guard() -> None:
        active = active_profiles()
        if both_stopped and active:
            raise Stopped('同步期间检测到 Claude 启动，已停止同步。')
        if not both_stopped and (len(active) != 1 or next(iter(active.values())) != source_key):
            raise Stopped('同步期间 Claude 的运行状态发生变化，已停止同步。')
    for src_key, dst_key in order:
        src, dst = paths[src_key], paths[dst_key]
        fingerprint = pair_key(src, dst)
        baseline = pairs.setdefault(fingerprint, {})
        if not isinstance(baseline, dict):
            baseline = {}
            pairs[fingerprint] = baseline
        counts = reconcile(src, dst, baseline, guard)
        total = [x + y for x, y in zip(total, counts)]
    # Establish pair baselines for records already equal through a third profile.
    # This permits a later direct switch between any two accounts without treating
    # their common, unchanged copy as an unknown conflict.
    checksums: dict[str, dict[str, str]] = {}
    for profile_key, folder in paths.items():
        checksums[profile_key] = {}
        for item in folder.iterdir():
            if not FILENAME.fullmatch(item.name):
                continue
            try:
                obj, _ = parse_record(item)
                if safe_session(obj):
                    checksums[profile_key][item.name] = digest(portable(obj))
            except (OSError, Problem, ValueError):
                continue
    keys = list(paths)
    for index, left in enumerate(keys):
        for right in keys[index + 1:]:
            fingerprint = pair_key(paths[left], paths[right])
            pair = pairs.setdefault(fingerprint, {})
            if not isinstance(pair, dict):
                pair = {}
                pairs[fingerprint] = pair
            for name in checksums[left].keys() & checksums[right].keys():
                if checksums[left][name] == checksums[right][name]:
                    pair[name] = checksums[left][name]
    result = {'ready': True, 'copied': total[0], 'conflicts': total[1],
              'skipped': total[2], 'at': int(time.time())}
    save_state('sync-state.json', {'pairs': pairs, 'last': result})
    return result


def profile_fingerprint(account: str, org: str) -> str:
    return hashlib.sha256((account.lower() + '\0' + org.lower()).encode('utf-8')).hexdigest()


def saved_usage(usage: Any, now: float | None = None) -> dict[str, Any] | None:
    if not isinstance(usage, dict):
        return None
    observed = usage.get('observed_at')
    current = time.time() if now is None else now
    if isinstance(observed, bool) or not isinstance(observed, (int, float)):
        return None
    try:
        observed = float(observed)
    except OverflowError:
        return None
    if not math.isfinite(observed):
        return None
    if observed <= 0 or observed > current + 300:
        return None
    values: dict[str, Any] = {}
    for name in ('five_hour', 'seven_day'):
        number = usage.get(name)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            values[name] = None
        else:
            try:
                value = float(number)
                values[name] = value if math.isfinite(value) and 0 <= value <= 100 else None
            except OverflowError:
                values[name] = None
        reset = usage.get(name + '_reset_at')
        if isinstance(reset, (int, float)) and not isinstance(reset, bool):
            try:
                reset_at = float(reset)
                if math.isfinite(reset_at) and 0 < reset_at < current + 366 * 86400:
                    values[name + '_reset_at'] = reset_at
                    if current >= reset_at:
                        values[name] = None
            except OverflowError:
                values[name] = None
    if all(value is None for value in values.values()):
        return None
    return {**values, 'observed_at': observed, 'stale': current - observed > 30 * 60}


def usage_config() -> dict[str, Any]:
    data = load_state('usage-state.json')
    if data.get('version') != 1 or not isinstance(data.get('profiles'), dict):
        return {'version': 1, 'enabled': False, 'profiles': {}}
    return {'version': 1, 'enabled': data.get('enabled') is True, 'profiles': data['profiles']}


def usage_profile(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data['profiles'].get(key)
    return dict(value) if isinstance(value, dict) else {}


@contextlib.contextmanager
def usage_locked() -> Iterator[None]:
    private_dir(STATE)
    fd = os.open(STATE / 'usage.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Problem('用量正在刷新，请稍后再试。') from exc
        yield
    finally:
        os.close(fd)


def usage_failure(code: str) -> Problem:
    return Problem({
        'usage_keychain': '无法访问 Claude 钥匙串，请允许访问后重试。',
        'usage_storage': '无法读取 Claude 的本机登录信息。',
        'usage_expired': '该账号的登录不可用或已过期，请在 Claude 中打开该账号后重试。',
        'usage_limited': 'Claude 限制了用量查询，请稍后再试。',
    }.get(code, '用量暂时不可用，请稍后再试。'))


def refresh_usage(key: str, allow_prompt: bool = False, now: float | None = None) -> dict[str, Any]:
    """Read an already-signed-in Desktop profile; never copy or persist its credentials."""
    if key not in DATA:
        raise Problem('未知账号。')
    current = time.time() if now is None else now
    with usage_locked():
        data = usage_config()
        if not data['enabled'] and not allow_prompt:
            return {'refreshed': False, 'reason': 'disabled'}
        profile = DATA[key]
        folder = session_dir(profile)
        account = account_id(profile)
        if folder is None or account is None:
            raise Problem('请先在 Claude Desktop 中登录并打开该账号的 Code。')
        fingerprint = profile_fingerprint(account, folder.name)
        record: dict[str, Any] = usage_profile(data, key)
        if record.get('profile') != fingerprint:
            record = {'profile': fingerprint}
        retry_at = record.get('retry_at')
        if isinstance(retry_at, (int, float)) and not isinstance(retry_at, bool) and current < retry_at:
            if record.get('last_error'):
                raise usage_failure(str(record['last_error']))
            return {'refreshed': False, 'reason': 'recent'}
        record.update({'profile': fingerprint, 'attempt_at': current})
        data['profiles'][key] = record
        save_state('usage-state.json', data)
        failure = 'usage_unavailable'
        retry = 900
        try:
            command = [str(USAGE_PROBE), '--desktop-usage-probe']
            payload = {'profile': str(profile), 'account': account, 'organization': folder.name,
                       'allow_prompt': allow_prompt}
            try:
                completed = subprocess.run(command, input=json.dumps(payload), capture_output=True, text=True,
                                           timeout=35, check=False)
                result = json.loads(completed.stdout)
            except (OSError, subprocess.SubprocessError, ValueError):
                raise usage_failure(failure)
            if not isinstance(result, dict) or completed.returncode != 0 or result.get('ok') is not True:
                if isinstance(result, dict):
                    reported = result.get('error_code')
                    if isinstance(reported, str) and reported in {
                            'usage_keychain', 'usage_storage', 'usage_expired', 'usage_limited'}:
                        failure = reported
                    seconds = result.get('retry_seconds')
                    if type(seconds) is int:
                        retry = min(max(seconds, 900), 86400)
                if failure in ('usage_keychain', 'usage_storage', 'usage_expired'):
                    retry = 30 if allow_prompt else 900
                raise usage_failure(failure)
            observation = result.get('usage')
            normalized = saved_usage(observation, current)
            if not isinstance(observation, dict) or normalized is None:
                raise usage_failure(failure)
            # The Desktop profile must still be the same after the network request.
            after_account, after_folder = account_id(profile), session_dir(profile)
            if after_account is None or after_folder is None or profile_fingerprint(after_account, after_folder.name) != fingerprint:
                failure = 'usage_expired'
                raise usage_failure(failure)
            clean: dict[str, Any] = {'observed_at': current}
            for name in ('five_hour', 'seven_day', 'five_hour_reset_at', 'seven_day_reset_at'):
                value = observation.get(name) if name.endswith('_reset_at') else normalized.get(name)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    try:
                        numeric = float(value)
                        if math.isfinite(numeric) and (0 <= numeric <= 100 if not name.endswith('_reset_at') else current < numeric < current + 366 * 86400):
                            clean[name] = numeric
                    except OverflowError:
                        pass
            if 'five_hour' not in clean and 'seven_day' not in clean:
                raise usage_failure(failure)
            record.update({'usage': clean, 'retry_at': current + 300, 'last_error': None, 'failures': 0})
            data['enabled'] = True
            data['profiles'][key] = record
            save_state('usage-state.json', data)
            return {'refreshed': True}
        except Problem:
            count = record.get('failures', 0)
            count = count + 1 if type(count) is int and 0 <= count < 10 else 1
            if failure == 'usage_limited':
                retry = max(retry, min(900 * 2 ** (count - 1), 7200))
            record.update({'last_error': failure, 'retry_at': current + retry, 'failures': count})
            data['profiles'][key] = record
            save_state('usage-state.json', data)
            raise


def read_desktop_usage(key: str, profile: Path, folder: Path | None,
                       now: float | None = None) -> dict[str, Any] | None:
    if folder is None:
        return None
    account = account_id(profile)
    record = usage_profile(usage_config(), key)
    if account is None or record.get('profile') != profile_fingerprint(account, folder.name):
        return None
    return saved_usage(record.get('usage'), now)


def usage_due(record: dict[str, Any], now: float) -> bool:
    attempt = record.get('attempt_at')
    retry_at = record.get('retry_at')
    if isinstance(retry_at, (int, float)) and not isinstance(retry_at, bool) and now < retry_at:
        return False
    return (not isinstance(attempt, (int, float)) or isinstance(attempt, bool) or
            now < attempt or now - attempt >= 300)


def usage_needs_check(key: str, data: dict[str, Any], now: float) -> bool:
    try:
        folder = session_dir(DATA[key])
        account = account_id(DATA[key])
    except (Problem, OSError):
        return False
    if folder is None or account is None:
        return False
    record = usage_profile(data, key)
    return record.get('profile') != profile_fingerprint(account, folder.name) or usage_due(record, now)


def usage_tick(now: float | None = None) -> None:
    current = time.time() if now is None else now
    data = usage_config()
    if not data['enabled']:
        return
    for key in DATA:
        if not usage_needs_check(key, data, current):
            continue
        try:
            refresh_usage(key, allow_prompt=False, now=current)
        except (Problem, OSError, subprocess.SubprocessError):
            pass
        return


def schedule_usage_tick() -> None:
    data = usage_config()
    if not data['enabled']:
        return
    now = time.time()
    if any(usage_needs_check(key, data, now) for key in DATA):
        try:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'usage-background'],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError:
            pass


def warmup_config() -> dict[str, Any]:
    # Deliberately do not reactivate schedules from the removed CLI-login flow.
    data = load_state('desktop-warmup.json')
    if data.get('version') != 2 or not isinstance(data.get('profiles'), dict):
        return {'version': 2, 'profiles': {}}
    return data


@contextlib.contextmanager
def warmup_locked() -> Iterator[None]:
    private_dir(STATE)
    fd = os.open(STATE / 'desktop-warmup.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WarmupProblem('warm_error_busy') from exc
        yield
    finally:
        os.close(fd)


def warmup_record(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data['profiles'].get(key)
    return dict(value) if isinstance(value, dict) else {}


def warmup_context(key: str) -> tuple[Path, str, str]:
    if key not in DATA:
        raise WarmupProblem('warm_error_account')
    profile = DATA[key]
    account, folder = account_id(profile), session_dir(profile)
    if account is None or folder is None:
        raise WarmupProblem('warm_error_account')
    return profile, account, folder.name


def warmup_clock(record: dict[str, Any], now: datetime.datetime) -> datetime.datetime | None:
    hour, minute = record.get('hour', 9), record.get('minute', 0)
    if type(hour) is not int or type(minute) is not int or not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def warmup_decision(record: dict[str, Any], now: datetime.datetime) -> str | None:
    if record.get('enabled') is not True:
        return None
    scheduled = warmup_clock(record, now)
    if scheduled is None:
        return None
    stamp = scheduled.timestamp()
    enabled_at = record.get('enabled_at', float('inf'))
    if not isinstance(enabled_at, (int, float)) or isinstance(enabled_at, bool) or stamp < enabled_at:
        return None
    run_key = scheduled.isoformat()
    if now < scheduled or record.get('scheduled_key') == run_key:
        return None
    return 'due' if (now - scheduled).total_seconds() <= 90 else 'missed'


def warmup_save(key: str, enabled: bool, hour: int, minute: int,
                now: datetime.datetime | None = None) -> dict[str, Any]:
    if type(hour) is not int or type(minute) is not int or not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise WarmupProblem('warm_error_time')
    _, account, organization = warmup_context(key)
    current = now or datetime.datetime.now().astimezone()
    with warmup_locked():
        data = warmup_config()
        record = warmup_record(data, key)
        record.update({'enabled': enabled, 'hour': hour, 'minute': minute,
                       'enabled_at': current.timestamp(), 'profile': profile_fingerprint(account, organization)})
        data['profiles'][key] = record
        save_state('desktop-warmup.json', data)
    return {'saved': True}


def warmup_public(now: datetime.datetime | None = None) -> dict[str, dict[str, Any]]:
    current = now or datetime.datetime.now().astimezone()
    data = warmup_config()
    result = {}
    for key in DATA:
        record = warmup_record(data, key)
        try:
            _, account, organization = warmup_context(key)
            matches = record.get('profile') == profile_fingerprint(account, organization)
        except (Problem, OSError):
            matches = False
        enabled = matches and record.get('enabled') is True
        scheduled = warmup_clock(record, current)
        if scheduled is not None and (scheduled <= current or scheduled.timestamp() < record.get('enabled_at', 0)):
            scheduled += datetime.timedelta(days=1)
        result[key] = {'enabled': enabled, 'hour': record.get('hour', 9), 'minute': record.get('minute', 0),
                       'next_at': scheduled.timestamp() if enabled and scheduled else None,
                       'last_status': record.get('last_status') if matches else None,
                       'last_at': record.get('last_at') if matches else None,
                       'last_error': record.get('last_error') if matches else None}
    return result


def warmup_execute(key: str, scheduled: bool = False, allow_prompt: bool = False,
                   now: datetime.datetime | None = None) -> dict[str, Any]:
    current = now or datetime.datetime.now().astimezone()
    stamp = current.timestamp()
    profile, account, organization = warmup_context(key)
    fingerprint = profile_fingerprint(account, organization)
    with warmup_locked():
        data = warmup_config()
        record = warmup_record(data, key)
        if scheduled and (record.get('profile') != fingerprint or warmup_decision(record, current) != 'due'):
            return {'sent': False, 'reason': 'not_due'}
        last = record.get('started_at', 0)
        if isinstance(last, (int, float)) and stamp - last < (120 if record.get('last_status') == 'running' else 60):
            raise WarmupProblem('warm_error_busy')
        if record.get('profile') != fingerprint:
            record['enabled'] = False
        record.update({'profile': fingerprint, 'started_at': stamp, 'last_status': 'running', 'last_error': None})
        if scheduled:
            clock = warmup_clock(record, current)
            record['scheduled_key'] = clock.isoformat() if clock else None
        data['profiles'][key] = record
        save_state('desktop-warmup.json', data)
    failure: str | None = 'warm_error_failed'
    try:
        folder = session_dir(profile)
        usage = read_desktop_usage(key, profile, folder, now=stamp)
        if usage and not usage['stale'] and any(usage.get(name) == 100 for name in ('five_hour', 'seven_day')):
            raise WarmupProblem('warm_error_limited')
        payload = {'profile': str(profile), 'account': account, 'organization': organization,
                   'allow_prompt': allow_prompt and not scheduled}
        completed = subprocess.run([str(USAGE_PROBE), '--desktop-warmup-probe'], input=json.dumps(payload),
                                   capture_output=True, text=True, timeout=100, check=False)
        try:
            response = json.loads(completed.stdout)
        except ValueError:
            response = None
        if completed.returncode != 0 or not isinstance(response, dict) or response.get('ok') is not True or response.get('sent') is not True:
            code = response.get('error_code') if isinstance(response, dict) else None
            accepted = {'usage_keychain', 'usage_storage', 'usage_expired', 'warm_error_runtime',
                        'warm_error_failed', 'warm_error_timeout', 'warm_error_limited'}
            raise WarmupProblem(code if isinstance(code, str) and code in accepted else 'warm_error_failed')
        failure = None
        return {'sent': True}
    except WarmupProblem as exc:
        failure = exc.code
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        failure = 'warm_error_timeout' if isinstance(exc, subprocess.TimeoutExpired) else 'warm_error_failed'
        raise WarmupProblem(failure) from exc
    finally:
        with warmup_locked():
            data = warmup_config()
            record = warmup_record(data, key)
            if record.get('started_at') == stamp:
                record.update({'last_status': 'sent' if failure is None else 'failed',
                               'last_error': failure, 'last_at': stamp})
                data['profiles'][key] = record
                save_state('desktop-warmup.json', data)


def schedule_warmup_tick(now: datetime.datetime | None = None) -> None:
    current = now or datetime.datetime.now().astimezone()
    due = []
    with warmup_locked():
        data = warmup_config()
        changed = False
        for key in DATA:
            record = warmup_record(data, key)
            try:
                _, account, organization = warmup_context(key)
            except (Problem, OSError):
                continue
            if record.get('profile') != profile_fingerprint(account, organization):
                continue
            decision = warmup_decision(record, current)
            if decision == 'due':
                due.append(key)
            elif decision == 'missed':
                clock = warmup_clock(record, current)
                record.update({'scheduled_key': clock.isoformat() if clock else None,
                               'last_status': 'missed', 'last_at': current.timestamp(), 'last_error': None})
                data['profiles'][key] = record
                changed = True
        if changed:
            save_state('desktop-warmup.json', data)
    for key in due:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'warmup-run', key, '--scheduled'],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def read_usage(profile: Path, session_folder: Path | None, now: float | None = None) -> dict[str, Any] | None:
    """Read the latest Desktop sample for this profile's unambiguous organization.

    These are cached utilization percentages, not a live API response or token counts.
    A missing, invalid or ambiguous observation must remain unknown.
    """
    if session_folder is None:
        return None
    # Samples identify an organization, not a person. If a profile has been used
    # by multiple accounts, an old sample cannot be attributed confidently.
    root = profile / 'claude-code-sessions'
    try:
        accounts = [p for p in root.iterdir() if p.is_dir() and not p.is_symlink()
                    and UUID_ONLY.fullmatch(p.name)]
    except OSError:
        return None
    if len(accounts) != 1 or accounts[0] != session_folder.parent:
        return None
    try:
        data = json.loads(read_regular(profile / 'plan-usage-history.json'))
    except (OSError, ValueError, Problem):
        return None
    if (not isinstance(data, dict) or type(data.get('version')) is not int
            or data['version'] not in (1, 2) or not isinstance(data.get('samples'), list)):
        return None
    current_time = time.time() if now is None else now
    candidates: list[tuple[float, dict[str, Any]]] = []
    for sample in data['samples']:
        if not isinstance(sample, dict) or sample.get('org') != session_folder.name:
            continue
        stamp, utilization = sample.get('t'), sample.get('u')
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not isinstance(utilization, dict):
            continue
        try:
            observed = float(stamp) / 1000 if stamp > 100_000_000_000 else float(stamp)
        except OverflowError:
            continue
        if not math.isfinite(observed) or observed <= 0 or observed > current_time + 300:
            continue
        candidates.append((observed, utilization))
    if not candidates:
        return None
    observed, utilization = max(candidates, key=lambda item: item[0])

    def percent(key: str) -> float | None:
        value = utilization.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            value = float(value)
        except OverflowError:
            return None
        return value if math.isfinite(value) and 0 <= value <= 100 else None

    five_hour, seven_day = percent('fh'), percent('sd')
    if five_hour is None and seven_day is None:
        return None
    return {'five_hour': five_hour, 'seven_day': seven_day,
            'observed_at': observed, 'stale': current_time - observed > 30 * 60}


def status() -> dict[str, Any]:
    rows = processes()
    active = active_profiles(rows)
    busy = sum(child_sessions(pid, rows) for pid in active)
    folders: dict[str, bool] = {}
    problem = ''
    found_paths: dict[str, Path | None] = {}
    for key, root in DATA.items():
        try:
            found_paths[key] = session_dir(root)
            folders[key] = found_paths[key] is not None
        except Problem as exc:
            folders[key] = False
            found_paths[key] = None
            problem = str(exc)
    ids = [p.parent.name.lower() for p in found_paths.values() if p is not None]
    if len(ids) != len(set(ids)):
        problem = '多个窗口使用了同一个 Claude 账号，请登录不同账号。'
    profiles = []
    usage_state = usage_config()
    for key, root in DATA.items():
        observations = [read_usage(root, found_paths[key]),
                        read_desktop_usage(key, root, found_paths[key])]
        usable = [item for item in observations if item is not None]
        usage = None
        if usable:
            latest = max(usable, key=lambda item: item['observed_at'])
            combined = dict(latest)
            # A newer Desktop history sample can update the percentage without
            # repeating the API's reset timestamps. Carry those within the same
            # window, then invalidate percentages whose reset has passed.
            for observation in sorted(usable, key=lambda item: item['observed_at']):
                for name in ('five_hour_reset_at', 'seven_day_reset_at'):
                    reset = observation.get(name)
                    if isinstance(reset, (int, float)) and reset > latest['observed_at']:
                        combined[name] = reset
            usage = saved_usage(combined)
        folder = found_paths[key]
        account = account_id(root) if folder is not None else None
        entry = usage_profile(usage_state, key)
        error = entry.get('last_error') if folder is not None and account is not None and entry.get('profile') == profile_fingerprint(account, folder.name) else None
        profiles.append({'id': key, 'configured': folders[key], 'active': key in active.values(),
                         'usage': usage,
                         'usage_error': error})
    return {'active': next(iter(active.values())) if len(active) == 1 else ('none' if not active else 'many'),
            'busy': busy, 'profiles': profiles, 'configured': folders,
            'warmup': warmup_public(),
            'desktop_usage_enabled': usage_state['enabled'],
            'last': load_state('sync-state.json').get('last', {}),
            'problem': problem, 'problem_code': error_code(problem) if problem else None}


def background() -> dict[str, Any]:
    with locked():
        current = active_profiles()
        if len(current) != 1 or next(iter(current.values())) not in DATA:
            return {'ready': False, 'message': 'Claude 未运行或同时运行了多个实例，暂不自动同步。'}
        return sync(next(iter(current.values())))


def launch_profile(target: str) -> None:
    if target != 'a':
        ensure_profile(DATA[target])
        cmd = ['/usr/bin/open', '-n', '-a', str(APP), '--args', '--user-data-dir=' + str(DATA[target])]
    else:
        cmd = ['/usr/bin/open', '-a', str(APP)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def switch(target: str, allow_quit: bool) -> dict[str, Any]:
    if target not in DATA:
        raise Problem('未知账号。')
    with locked():
        current = active_profiles()
        if len(current) > 1 or 'unknown' in current.values():
            raise Problem('发现多个或未知的 Claude 窗口；请先只保留本工具管理的一个窗口。')
        source = next(iter(current.values()), None)
        if source == target:
            return {'message': '该账号已经打开。', 'already': True}
        target_ready = session_dir(DATA[target]) is not None
        if current:
            if not allow_quit:
                raise Problem('切换需要先退出当前 Claude；请在界面中确认。')
            pid = next(iter(current))
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and active_profiles():
                time.sleep(0.25)
            if active_profiles():
                raise Problem('Claude 未能正常退出，已停止切换，没有强制结束。')
        try:
            result = sync(source, both_stopped=True)
            if active_profiles():
                raise Problem('发现 Claude 又被启动，已停止切换。')
            launch_profile(target)
        except (Problem, OSError, subprocess.SubprocessError):
            # If the handoff fails after quitting, restore the previous window when
            # there is no competing instance. Never force a second Claude to open.
            if source and not active_profiles():
                try:
                    launch_profile(source)
                except (Problem, OSError, subprocess.SubprocessError):
                    pass
            raise
        msg = 'Claude 已启动。'
        if not target_ready:
            msg += ' 首次使用此账号时，请在新窗口登录并打开 Code；随后退出并重新打开该账号，会自动汇合会话列表。'
        elif result['conflicts'] or result['skipped']:
            msg += f" 同步保留了 {result['conflicts']} 个冲突、跳过 {result['skipped']} 个特殊或异常会话。"
        return {'message': msg, 'sync': result, 'needs_login': not target_ready,
                'issues': bool(result.get('conflicts') or result.get('skipped'))}


def error_code(message: str) -> str:
    if '用量正在刷新' in message:
        return 'usage_error_busy'
    if '钥匙串' in message:
        return 'usage_keychain'
    if '本机登录信息' in message:
        return 'usage_storage'
    if '登录不可用或已过期' in message:
        return 'usage_expired'
    if '限制了用量查询' in message:
        return 'usage_limited'
    if '用量暂时不可用' in message:
        return 'usage_unavailable'
    if 'Desktop 中登录' in message:
        return 'usage_expired'
    if '多个或未知' in message:
        return 'error_multiple'
    if '同一个 Claude 账号' in message:
        return 'error_duplicate'
    if '多个组织' in message:
        return 'error_org'
    if '未能正常退出' in message:
        return 'error_timeout'
    if '另一个同步' in message:
        return 'error_busy'
    if '最多支持' in message:
        return 'error_limit'
    return 'error_generic'


def main() -> int:
    global DATA
    DATA = discover_profiles()
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['status', 'background', 'switch', 'add',
                                            'usage-refresh', 'usage-background', 'warmup-save', 'warmup-run'])
    parser.add_argument('target', nargs='?')
    parser.add_argument('--allow-quit', action='store_true')
    parser.add_argument('--allow-keychain-prompt', action='store_true')
    parser.add_argument('--enabled', choices=['yes', 'no'], default='no')
    parser.add_argument('--hour', type=int, default=9)
    parser.add_argument('--minute', type=int, default=0)
    parser.add_argument('--scheduled', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'status':
            output = status()
        elif args.command == 'background':
            try:
                output = background()
            finally:
                try:
                    schedule_usage_tick()
                finally:
                    schedule_warmup_tick()
        elif args.command == 'usage-background':
            usage_tick()
            output = {}
        elif args.command == 'usage-refresh' and args.target:
            output = refresh_usage(args.target, allow_prompt=args.allow_keychain_prompt)
        elif args.command == 'warmup-save' and args.target:
            output = warmup_save(args.target, args.enabled == 'yes', args.hour, args.minute)
        elif args.command == 'warmup-run' and args.target:
            output = warmup_execute(args.target, scheduled=args.scheduled, allow_prompt=args.allow_keychain_prompt)
        elif args.command == 'add':
            output = add_profile()
        elif args.command == 'switch' and args.target:
            output = switch(args.target, args.allow_quit)
        else:
            raise Problem('请选择账号 A 或 B。')
        print(json.dumps({'ok': True, **output}, ensure_ascii=False))
        return 0
    except (Problem, OSError, subprocess.SubprocessError) as exc:
        # Do not print subprocess output or contents of account configuration files.
        message = str(exc) if isinstance(exc, Problem) else '本地操作失败，请检查 Claude 状态后重试。'
        code = exc.code if isinstance(exc, WarmupProblem) else error_code(message)
        print(json.dumps({'ok': False, 'message': message, 'error_code': code}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
