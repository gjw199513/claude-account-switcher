#!/usr/bin/env python3
"""Local Claude Desktop profiles and conservative Code-session reconciliation.

This uses macOS, Python's standard library, and the existing Claude installation.
It never extracts, saves, moves or copies browser cookies or OAuth tokens.
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
import shlex
import shutil
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


@contextlib.contextmanager
def warmup_locked() -> Iterator[None]:
    """Serialize settings and daily claims without blocking session synchronization."""
    private_dir(STATE)
    fd = os.open(STATE / 'warmup.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def warmup_config() -> dict[str, Any]:
    data = load_state('warmup.json')
    profiles = data.get('profiles')
    if data.get('version') != 1 or not isinstance(profiles, dict):
        return {'version': 1, 'profiles': {}}
    return {'version': 1, 'profiles': profiles, 'last_tick_at': data.get('last_tick_at')}


def warmup_profile(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data['profiles'].get(key)
    return dict(value) if isinstance(value, dict) else {}


def warmup_cli() -> str | None:
    candidates = [STATE / 'cli-runtime/node_modules/.bin/claude', Path.home() / '.local/bin/claude',
                  Path('/opt/homebrew/bin/claude'), Path('/usr/local/bin/claude')]
    candidates.extend(sorted((Path.home() / '.nvm/versions/node').glob('*/bin/claude'), reverse=True))
    discovered = shutil.which('claude')
    if discovered:
        candidates.append(Path(discovered))
    return next((str(p) for p in candidates if p.is_file() and os.access(p, os.X_OK)), None)


def warmup_env(key: str) -> dict[str, str]:
    if key not in DATA:
        raise Problem('未知账号。')
    private_dir(STATE / 'warmup-cli')
    directory = STATE / 'warmup-cli' / key
    private_dir(directory)
    env = {name: os.environ[name] for name in ('HOME', 'USER', 'LOGNAME', 'LANG', 'TMPDIR', 'TERM', 'COLORTERM',
           'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy',
           'all_proxy', 'no_proxy') if name in os.environ}
    env.update({'HOME': str(Path.home()), 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin',
                'CLAUDE_CONFIG_DIR': str(directory), 'DISABLE_AUTOUPDATER': '1'})
    return env


def warmup_identity(key: str) -> dict[str, str]:
    """Ask the unmodified CLI for non-secret identity metadata, never for tokens."""
    cli = warmup_cli()
    if not cli:
        raise Problem('预热需要安装 Claude Code CLI。')
    if key not in DATA:
        raise Problem('未知账号。')
    folder = session_dir(DATA[key])
    account = account_id(DATA[key])
    if folder is None or account is None:
        raise Problem('请先在 Claude Desktop 中登录并打开该账号的 Code。')
    env = warmup_env(key)
    try:
        result = subprocess.run([cli, 'auth', 'status'], env=env, cwd=str(STATE),
                                capture_output=True, text=True, timeout=15, check=False)
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise Problem('无法读取 Claude Code 的登录状态。')
    if not isinstance(payload, dict) or result.returncode != 0 or payload.get('loggedIn') is not True:
        raise Problem('请先登录该账号的 Claude Code CLI。')
    if payload.get('authMethod') != 'claude.ai' or payload.get('apiProvider') != 'firstParty':
        raise Problem('预热只支持通过 Claude 订阅登录的官方 CLI。')
    if payload.get('configDirectory') != env['CLAUDE_CONFIG_DIR']:
        raise Problem('Claude Code 未提供可确认的账号信息。')
    email, org = payload.get('email'), payload.get('orgId')
    if not isinstance(email, str) or not email.strip() or not isinstance(org, str) or not UUID_ONLY.fullmatch(org):
        raise Problem('Claude Code 未提供可确认的账号信息。')
    if org.lower() != folder.name.lower():
        raise Problem('CLI 登录的组织与所选桌面账号不一致。')
    return {'email': email.strip(), 'org': org.lower(), 'account': account.lower(), 'cli': cli}


def identity_fingerprint(identity: dict[str, str]) -> str:
    value = '\0'.join(identity[k].lower() for k in ('email', 'org', 'account'))
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def profile_fingerprint(account: str, org: str) -> str:
    return hashlib.sha256((account.lower() + '\0' + org.lower()).encode('utf-8')).hexdigest()


def warmup_info(key: str) -> dict[str, Any]:
    if key not in DATA:
        raise Problem('未知账号。')
    result: dict[str, Any] = {'cli_available': warmup_cli() is not None, 'email': None, 'identity_error': None,
                              'bound': False}
    try:
        identity = warmup_identity(key)
        result['email'] = identity['email']
        result['bound'] = warmup_profile(warmup_config(), key).get('binding') == identity_fingerprint(identity)
    except Problem as exc:
        result['identity_error'] = error_code(str(exc))
    return result


def warmup_login_command(key: str) -> dict[str, Any]:
    cli = warmup_cli()
    if not cli:
        raise Problem('预热需要安装 Claude Code CLI。')
    env = warmup_env(key)
    # The official binary manages its own credentials; the switcher never reads them.
    forwarded = ('HOME', 'USER', 'LOGNAME', 'LANG', 'TMPDIR', 'TERM', 'COLORTERM', 'TERM_PROGRAM', 'HTTP_PROXY', 'HTTPS_PROXY',
                 'ALL_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')
    exports = ' '.join(f'{name}="${{{name}:-}}"' for name in forwarded)
    fixed = ' PATH=/usr/bin:/bin:/usr/sbin:/sbin DISABLE_AUTOUPDATER=1 CLAUDE_CONFIG_DIR='
    content = '#!/bin/bash\n/usr/bin/env -i ' + exports + fixed + shlex.quote(env['CLAUDE_CONFIG_DIR'])
    content += ' ' + shlex.quote(cli) + ' auth login\n'
    content += "printf '\\n%s\\n' 'Return to Claude Account Switcher after login.'\n"
    path = STATE / ('warmup-login-' + key + '.command')
    prior = read_regular(path) if path.exists() else None
    atomic_write(path, content.encode(), prior)
    path.chmod(0o700)
    return {'login_command': str(path)}


def warmup_bind(key: str) -> dict[str, Any]:
    identity = warmup_identity(key)
    with warmup_locked():
        data = warmup_config()
        record = warmup_profile(data, key)
        binding = identity_fingerprint(identity)
        if record.get('binding') != binding:
            record.pop('usage', None)
        record['binding'] = binding
        record['profile'] = profile_fingerprint(identity['account'], identity['org'])
        # A newly confirmed identity starts with scheduling turned off.
        record['enabled'] = False
        data['profiles'][key] = record
        save_state('warmup.json', data)
    return {'bound': True}


def warmup_save(key: str, enabled: bool, hour: int, minute: int,
                now: datetime.datetime | None = None) -> dict[str, Any]:
    if key not in DATA or type(hour) is not int or type(minute) is not int or not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise Problem('预热时间不正确。')
    with warmup_locked():
        data = warmup_config()
        record = warmup_profile(data, key)
        if enabled and not record.get('binding'):
            raise Problem('请先确认预热账号。')
        if (record.get('enabled') is not enabled or record.get('hour') != hour or record.get('minute') != minute):
            record['enabled_at'] = (now or datetime.datetime.now()).timestamp()
            record.pop('missed_date', None)
        record.update({'enabled': enabled, 'hour': hour, 'minute': minute})
        data['profiles'][key] = record
        save_state('warmup.json', data)
    return {'saved': True}


def warmup_due(record: dict[str, Any], now: datetime.datetime) -> float | None:
    hour, minute = record.get('hour'), record.get('minute')
    if (record.get('enabled') is not True or not record.get('binding') or
            type(hour) is not int or type(minute) is not int or not (0 <= hour <= 23 and 0 <= minute <= 59) or
            record.get('last_date') == now.date().isoformat()):
        return None
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    seconds = (now - scheduled).total_seconds()
    return seconds if seconds >= 0 else None


def warmup_public(now: datetime.datetime | None = None) -> dict[str, dict[str, Any]]:
    now = now or datetime.datetime.now()
    data = warmup_config()
    result = {}
    for key in DATA:
        record = warmup_profile(data, key)
        due = warmup_due(record, now)
        result[key] = {'enabled': record.get('enabled') is True, 'hour': record.get('hour', 9),
                       'minute': record.get('minute', 0), 'bound': bool(record.get('binding')),
                       'last_status': record.get('last_status'),
                       'pending': due is not None and (due > 90 or record.get('missed_date') == now.date().isoformat())}
    return result


def warmup_execute(key: str, reason: str, now: datetime.datetime | None = None) -> dict[str, Any]:
    now = now or datetime.datetime.now()
    today = now.date().isoformat()
    if key not in DATA or reason not in ('scheduled', 'manual', 'catchup'):
        raise Problem('未知账号。')
    with warmup_locked():
        data = warmup_config()
        record = warmup_profile(data, key)
        if not record.get('binding'):
            raise Problem('请先确认预热账号。')
        if record.get('last_status') == 'running' and record.get('last_date') == today:
            started = record.get('started_at')
            if not isinstance(started, (int, float)) or time.time() - started < 180:
                raise Problem('预热正在进行。')
        if reason != 'manual':
            due = warmup_due(record, now)
            missed = due is not None and (due > 90 or record.get('missed_date') == today)
            if due is None or (reason == 'scheduled' and missed) or (reason == 'catchup' and not missed):
                raise Problem('当前没有需要执行的预热。')
        record.update({'last_date': today, 'last_status': 'running', 'started_at': time.time()})
        data['profiles'][key] = record
        save_state('warmup.json', data)
    success = False
    usage: dict[str, Any] | None = None
    try:
        identity = warmup_identity(key)
        if identity_fingerprint(identity) != record['binding']:
            raise Problem('CLI 登录账号发生变化，请重新确认。')
        with warmup_locked():
            current = warmup_profile(warmup_config(), key)
            if (current.get('binding') != record.get('binding') or
                    (reason != 'manual' and current.get('enabled') is not True)):
                raise Problem('预热设置已更改，请重新操作。')
        command = [identity['cli'], '-p', '--safe-mode', '--tools', '', '--disallowed-tools', '*',
                   '--strict-mcp-config', '--model', 'haiku', '--max-turns', '1',
                   '--no-session-persistence', '--output-format', 'stream-json', '--verbose', '--system-prompt',
                   'Reply only with OK.', 'Reply OK.']
        completed = subprocess.run(command, env=warmup_env(key), cwd=str(STATE),
                                   capture_output=True, text=True, timeout=120, check=False)
        usage, completed_ok = parse_warmup_stream(completed.stdout)
        success = completed.returncode == 0 and completed_ok
    finally:
        with warmup_locked():
            data = warmup_config()
            current = warmup_profile(data, key)
            if current.get('last_date') == today and current.get('last_status') == 'running':
                current['last_status'] = 'success' if success else 'failed'
                if success and usage is not None and current.get('binding') == record.get('binding'):
                    current['usage'] = usage
                data['profiles'][key] = current
                save_state('warmup.json', data)
    return {'sent': success, 'result': 'success' if success else 'failed'}


def parse_warmup_stream(stdout: str, now: float | None = None) -> tuple[dict[str, Any] | None, bool]:
    """Keep only utilization from a CLI event, never prompts, replies, or credentials."""
    observation: dict[str, Any] | None = None
    success = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get('type') == 'result':
            success = event.get('is_error') is False
        if event.get('type') != 'rate_limit_event':
            continue
        info = event.get('rate_limit_info')
        windows = info.get('unifiedWindows') if isinstance(info, dict) else None
        if not isinstance(windows, dict):
            continue
        values: dict[str, float | None] = {}
        for source, target in (('five_hour', 'five_hour'), ('seven_day', 'seven_day')):
            window = windows.get(source)
            value = window.get('utilization') if isinstance(window, dict) else None
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                values[target] = None
            else:
                try:
                    number = float(value)
                    values[target] = number * 100 if math.isfinite(number) and 0 <= number <= 1 else None
                except OverflowError:
                    values[target] = None
        if values['five_hour'] is not None or values['seven_day'] is not None:
            observation = {**values, 'observed_at': time.time() if now is None else now}
    return observation, success


def read_warmup_usage(key: str, profile: Path, session_folder: Path | None,
                      now: float | None = None) -> dict[str, Any] | None:
    if session_folder is None:
        return None
    account = account_id(profile)
    record = warmup_profile(warmup_config(), key)
    if account is None or record.get('profile') != profile_fingerprint(account, session_folder.name):
        return None
    usage = record.get('usage')
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
    values = {}
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
    if all(value is None for value in values.values()):
        return None
    return {**values, 'observed_at': observed, 'stale': current - observed > 30 * 60}


def warmup_dismiss(key: str, now: datetime.datetime | None = None) -> dict[str, Any]:
    now = now or datetime.datetime.now()
    with warmup_locked():
        data = warmup_config()
        record = warmup_profile(data, key)
        due = warmup_due(record, now)
        if due is not None and (due > 90 or record.get('missed_date') == now.date().isoformat()):
            record.update({'last_date': now.date().isoformat(), 'last_status': 'skipped'})
            data['profiles'][key] = record
            save_state('warmup.json', data)
    return {'dismissed': True}


def warmup_tick(now: datetime.datetime | None = None) -> None:
    now = now or datetime.datetime.now()
    current = now.timestamp()
    due_keys = []
    with warmup_locked():
        data = warmup_config()
        previous = data.get('last_tick_at')
        for key in DATA:
            record = warmup_profile(data, key)
            due = warmup_due(record, now)
            if due is None:
                continue
            scheduled = current - due
            enabled_at = record.get('enabled_at')
            active_at_schedule = (isinstance(previous, (int, float)) and not isinstance(previous, bool) and
                                  scheduled - 45 <= previous < scheduled and current - previous <= 60 and
                                  isinstance(enabled_at, (int, float)) and not isinstance(enabled_at, bool) and
                                  enabled_at <= scheduled)
            if due <= 90 and active_at_schedule and record.get('missed_date') != now.date().isoformat():
                due_keys.append(key)
            else:
                record['missed_date'] = now.date().isoformat()
                data['profiles'][key] = record
        data['last_tick_at'] = current
        save_state('warmup.json', data)
    for key in due_keys:
        try:
            warmup_execute(key, 'scheduled', now)
        except (Problem, OSError, subprocess.SubprocessError):
            # A failed attempt is recorded; never retry automatically that day.
            continue


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
    for key, root in DATA.items():
        observations = [read_usage(root, found_paths[key]), read_warmup_usage(key, root, found_paths[key])]
        usable = [item for item in observations if item is not None]
        profiles.append({'id': key, 'configured': folders[key], 'active': key in active.values(),
                         'usage': max(usable, key=lambda item: item['observed_at']) if usable else None})
    return {'active': next(iter(active.values())) if len(active) == 1 else ('none' if not active else 'many'),
            'busy': busy, 'profiles': profiles, 'configured': folders,
            'warmup': warmup_public(),
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
    if '预热需要安装' in message:
        return 'warm_error_cli_missing'
    if '登录该账号的 Claude Code CLI' in message:
        return 'warm_error_login'
    if '组织与所选桌面账号不一致' in message or '登录账号发生变化' in message:
        return 'warm_error_mismatch'
    if '可确认的账号信息' in message or '订阅登录的官方 CLI' in message:
        return 'warm_error_identity'
    if '桌面账号' in message or 'Desktop 中登录' in message:
        return 'warm_error_desktop'
    if '确认预热账号' in message:
        return 'warm_error_confirm'
    if '预热正在进行' in message:
        return 'warm_error_running'
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
    parser.add_argument('command', choices=['status', 'background', 'switch', 'add', 'warmup-info',
                                            'warmup-login', 'warmup-bind', 'warmup-save',
                                            'warmup-run', 'warmup-dismiss'])
    parser.add_argument('target', nargs='?')
    parser.add_argument('--allow-quit', action='store_true')
    parser.add_argument('--enabled', choices=['yes', 'no'], default='no')
    parser.add_argument('--hour', type=int, default=9)
    parser.add_argument('--minute', type=int, default=0)
    parser.add_argument('--reason', choices=['manual', 'catchup'], default='manual')
    args = parser.parse_args()
    try:
        if args.command == 'status':
            output = status()
        elif args.command == 'background':
            try:
                output = background()
            finally:
                warmup_tick()
        elif args.command == 'add':
            output = add_profile()
        elif args.command == 'switch' and args.target:
            output = switch(args.target, args.allow_quit)
        elif args.command == 'warmup-info' and args.target:
            output = warmup_info(args.target)
        elif args.command == 'warmup-login' and args.target:
            output = warmup_login_command(args.target)
        elif args.command == 'warmup-bind' and args.target:
            output = warmup_bind(args.target)
        elif args.command == 'warmup-save' and args.target:
            output = warmup_save(args.target, args.enabled == 'yes', args.hour, args.minute)
        elif args.command == 'warmup-run' and args.target:
            output = warmup_execute(args.target, args.reason)
        elif args.command == 'warmup-dismiss' and args.target:
            output = warmup_dismiss(args.target)
        else:
            raise Problem('请选择账号 A 或 B。')
        print(json.dumps({'ok': True, **output}, ensure_ascii=False))
        return 0
    except (Problem, OSError, subprocess.SubprocessError) as exc:
        # Do not print subprocess output or contents of account configuration files.
        message = str(exc) if isinstance(exc, Problem) else '本地操作失败，请检查 Claude 状态后重试。'
        print(json.dumps({'ok': False, 'message': message, 'error_code': error_code(message)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
