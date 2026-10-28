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
            key(account, organization, "user:inference"): ["token": "wrong-scope", "expiresAt": (now + 7200) * 1000],
        ]
        precondition(DesktopUsage.matchingToken(entries, account: account, organization: organization, now: now) == "profile-fixture")
        precondition(DesktopUsage.matchingToken(entries, account: account, organization: organization, now: now + 7200) == nil)
        precondition(DesktopUsage.matchingToken(entries, account: otherAccount, organization: otherOrg, now: now) == nil)

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
