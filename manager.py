#!/usr/bin/env python3
"""Local Claude Desktop profiles and conservative Code-session reconciliation.

This uses macOS, Python's standard library, and the existing Claude installation.
It never extracts, saves, moves or copies browser cookies or OAuth tokens.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
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
    profiles = [{'id': key, 'configured': folders[key], 'active': key in active.values()}
                for key in DATA]
    return {'active': next(iter(active.values())) if len(active) == 1 else ('none' if not active else 'many'),
            'busy': busy, 'profiles': profiles, 'configured': folders,
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
    parser.add_argument('command', choices=['status', 'background', 'switch', 'add'])
    parser.add_argument('target', nargs='?')
    parser.add_argument('--allow-quit', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'status':
            output = status()
        elif args.command == 'background':
            output = background()
        elif args.command == 'add':
            output = add_profile()
        elif args.target:
            output = switch(args.target, args.allow_quit)
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
