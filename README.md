<p align="center"><img src="assets/icon.png" alt="Claude Account Switcher icon" width="116"></p>

# Claude Account Switcher

A small, unofficial macOS app to switch between Claude Desktop accounts and keep local Code sessions visible. Each account is signed in separately; only one Claude window runs at a time.

[简体中文](docs/README.zh-CN.md) · [日本語](docs/README.ja.md) · [한국어](docs/README.ko.md) · [Español](docs/README.es.md) · [Français](docs/README.fr.md) · [Deutsch](docs/README.de.md)

![Account selection window](assets/screenshot.png)

## Install

Requires macOS, Claude Desktop in `/Applications`, Xcode Command Line Tools, and `/usr/bin/python3` 3.9 or later. Build locally:

```sh
git clone https://github.com/gjw199513/claude-account-switcher.git
cd claude-account-switcher
./install.sh
```

Open **Claude Account Switcher** from `~/Applications`. The interface follows the macOS language, with English, Simplified Chinese, Japanese, Korean, Spanish, French, and German available.

## Use

1. Your current Claude profile is **Account A**. Click **Add account**, confirm the switch, and sign in to the new account in Claude. Open its **Code** tab.
2. On the first login, quit Claude with `⌘Q`, then select that account and click **Switch** once more to load the shared session list.
3. Later, select an account and click **Switch**. Claude closes normally, the local session index is reconciled automatically, and the selected account opens. Finish or save active work before switching.

Additional accounts can be added the same way. Login expiration may still require signing in again.

## How it works and limits

- Each profile has its own Claude data directory. Claude handles sign-in; the app does not export, copy, or replace login credentials. It uses no proxy and does not switch accounts based on quota.
- Local Code transcripts remain in the shared `~/.claude/projects` directory. A background task and the switch operation reconcile account-specific sidebar index files. Claude may need a restart to reload its list.
- Claude cloud chats, Cowork sessions, account quotas, and account-specific connectors are separate. Connectors are not copied between accounts. Desktop-specific settings are not merged.
- SSH, WSL, custom worktrees and other special or unrecognized sessions may be skipped. Existing local scratch workspaces keep their original paths; deleting a profile directory can break sessions that use it. Multiple organization folders stop automatic sync instead of guessing.
- Conflicting or malformed records are preserved; overwritten index records are backed up locally. Deletions are not propagated. This relies on Claude Desktop's undocumented storage layout and may break after updates.

**Validation:** the current macOS installation displayed Account A's local Code sidebar in Account B. Synthetic tests cover multi-account reconciliation and safety checks. Continuing a real conversation across accounts and other Claude versions has not yet been fully validated.

## Uninstall

Run `./uninstall.sh`. Claude profiles, conversations, and local backups remain on disk.

## License

[MIT](LICENSE). This project is independent and is not affiliated with or endorsed by Anthropic.
