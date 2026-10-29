import Foundation

@main
struct DesktopUsageTests {
    static func main() throws {
        // Produced independently with OpenSSL and a synthetic password.
        let encrypted = "djEwo081o7dagC6klAeC0FaBVleMVUkdjevRCaPgHGhp2Mo="
        let cache = try DesktopUsage.decryptCache(encrypted, password: Data("fixture-password".utf8))
        precondition(cache["sentinel"] as? String == "ok")
        do {
            _ = try DesktopUsage.decryptCache(encrypted, password: Data("wrong-password".utf8))
            fatalError("invalid key must not decrypt")
        } catch { }

        let account = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        let otherAccount = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        let organization = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        let otherOrg = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        func key(_ account: String, _ org: String, _ scopes: String) -> String {
            "acct:\(account)|member:\(org):https://api.anthropic.com:\(scopes)"
        }
        let now = 1_800_000_000.0
        let entries: [String: Any] = [
            key(account, organization, "user:profile"): ["token": "profile-fixture", "expiresAt": (now + 3600) * 1000],
            key(account, organization, "user:profile user:inference"): ["token": "broader-fixture", "expiresAt": (now + 7200) * 1000],
            key(otherAccount, organization, "user:profile"): ["token": "wrong-account", "expiresAt": (now + 7200) * 1000],
            key(account, otherOrg, "user:profile"): ["token": "wrong-org", "expiresAt": (now + 7200) * 1000],
            key(account, organization, "user:inference"): ["token": "inference-fixture", "expiresAt": (now + 7200) * 1000],
        ]
        precondition(DesktopUsage.matchingToken(entries, account: account, organization: organization, now: now) == "profile-fixture")
        precondition(DesktopUsage.matchingToken(entries, account: account, organization: organization, now: now + 7200) == nil)
        precondition(DesktopUsage.matchingToken(entries, account: otherAccount, organization: otherOrg, now: now) == nil)
        precondition(DesktopUsage.matchingToken(entries, account: account, organization: organization,
                                               now: now, requiredScopes: ["user:inference"]) == "inference-fixture")
        precondition(DesktopUsage.matchingToken(entries, account: account, organization: organization,
                                               now: now, requiredScopes: ["missing:scope"]) == nil)

        let isolated = FileManager.default.temporaryDirectory.appendingPathComponent("unused-fixture-directory")
        let environment = DesktopWarmup.environment(token: "fixture-token", directory: isolated, inherited: [
            "HOME": NSHomeDirectory(), "ANTHROPIC_API_KEY": "never-use-api-credit",
            "ANTHROPIC_BASE_URL": "https://invalid.example", "CLAUDE_CODE_USE_BEDROCK": "1",
            "CLAUDE_CONFIG_DIR": "/wrong/account", "CLAUDE_CODE_OAUTH_TOKEN": "wrong-account-token"])
        precondition(environment["ANTHROPIC_API_KEY"] == nil)
        precondition(environment["ANTHROPIC_BASE_URL"] == nil)
        precondition(environment["CLAUDE_CODE_USE_BEDROCK"] == nil)
        precondition(environment["CLAUDE_CODE_OAUTH_TOKEN"] == "fixture-token")
        precondition(environment["CLAUDE_CONFIG_DIR"] == isolated.path)

        let fixture = FileManager.default.temporaryDirectory.appendingPathComponent("warmup-fixture-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: fixture, withIntermediateDirectories: false,
                                                attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: fixture) }
        let fakeCLI = fixture.appendingPathComponent("claude-code/2.1.309/fixture/claude.app/Contents/MacOS/claude")
        try FileManager.default.createDirectory(at: fakeCLI.deletingLastPathComponent(), withIntermediateDirectories: true)
        try """
        #!/usr/bin/python3
        import json, os, sys
        assert os.environ['CLAUDE_CODE_OAUTH_TOKEN'] == 'fixture-token'
        assert not os.environ.get('ANTHROPIC_API_KEY')
        assert not os.environ.get('ANTHROPIC_BASE_URL')
        assert os.path.realpath(os.getcwd()) == os.path.realpath(os.environ['CLAUDE_CONFIG_DIR'])
        assert '--safe-mode' in sys.argv and '--no-session-persistence' in sys.argv
        assert sys.argv[sys.argv.index('--tools') + 1] == ''
        print(json.dumps({'type':'result', 'subtype':'success', 'is_error':False, 'result':'OK'}))
        """.write(to: fakeCLI, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: fakeCLI.path)
        let discoveredCLI = try DesktopWarmup.cli(in: fixture.path)
        precondition(discoveredCLI == fakeCLI)
        try DesktopWarmup.execute(cli: fakeCLI, token: "fixture-token")

        let response = Data("""
        {"five_hour":{"utilization":0,"resets_at":"2030-01-01T00:00:00Z"},
         "seven_day":{"utilization":42.5,"resets_at":"2030-01-02T00:00:00Z"}}
        """.utf8)
        let usage = DesktopUsage.parseUsage(response, now: now)!
        precondition(usage["five_hour"] as? Double == 0)
        precondition(usage["seven_day"] as? Double == 42.5)
        precondition(usage["five_hour_reset_at"] as? Double == 1_893_456_000)
        precondition(DesktopUsage.parseUsage(response, now: 1_893_542_401) == nil)
        let invalid = Data("""
        {"five_hour":{"utilization":true},"seven_day":{"utilization":101}}
        """.utf8)
        precondition(DesktopUsage.parseUsage(invalid, now: now) == nil)
        print("Desktop usage fixtures passed")
    }
}
