import CommonCrypto
import Foundation
import LocalAuthentication
import Security

// The desktop login is decrypted only in this short-lived process. Nothing sent
// to the parent process includes a credential, and only Anthropic receives it.
enum DesktopUsage {
    struct Failure: Error {
        let code: String
        var retrySeconds: Int? = nil
    }

    private final class NoRedirect: NSObject, URLSessionTaskDelegate {
        func urlSession(_ session: URLSession, task: URLSessionTask,
                        willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                        completionHandler: @escaping (URLRequest?) -> Void) {
            completionHandler(nil)
        }
    }

    static func deriveKey(password: Data) throws -> Data {
        let salt = Data("saltysalt".utf8)
        var key = Data(count: kCCKeySizeAES128)
        let keyLength = key.count
        let status = key.withUnsafeMutableBytes { output in
            salt.withUnsafeBytes { saltBytes in
                password.withUnsafeBytes { passBytes in
                    CCKeyDerivationPBKDF(CCPBKDFAlgorithm(kCCPBKDF2),
                        passBytes.baseAddress?.assumingMemoryBound(to: Int8.self), password.count,
                        saltBytes.baseAddress?.assumingMemoryBound(to: UInt8.self), salt.count,
                        CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA1), 1003,
                        output.baseAddress?.assumingMemoryBound(to: UInt8.self), keyLength)
                }
            }
        }
        guard status == kCCSuccess else { throw Failure(code: "usage_storage") }
        return key
    }

    static func decryptCache(_ encoded: String, password: Data) throws -> [String: Any] {
        guard let data = Data(base64Encoded: encoded), data.count > 3,
              data.prefix(3) == Data("v10".utf8) else { throw Failure(code: "usage_storage") }
        var key = try deriveKey(password: password)
        defer { key.resetBytes(in: 0..<key.count) }
        let cipher = Data(data.dropFirst(3))
        let iv = Data(repeating: 0x20, count: kCCBlockSizeAES128)
        var plaintext = Data(count: cipher.count + kCCBlockSizeAES128)
        var written = 0
        let capacity = plaintext.count
        let status = plaintext.withUnsafeMutableBytes { output in
            key.withUnsafeBytes { keyBytes in
                iv.withUnsafeBytes { ivBytes in
                    cipher.withUnsafeBytes { input in
                        CCCrypt(CCOperation(kCCDecrypt), CCAlgorithm(kCCAlgorithmAES),
                            CCOptions(kCCOptionPKCS7Padding), keyBytes.baseAddress, key.count,
                            ivBytes.baseAddress, input.baseAddress, cipher.count,
                            output.baseAddress, capacity, &written)
                    }
                }
            }
        }
        guard status == kCCSuccess else { throw Failure(code: "usage_storage") }
        plaintext.count = written
        defer { plaintext.resetBytes(in: 0..<plaintext.count) }
        guard let object = try? JSONSerialization.jsonObject(with: plaintext) as? [String: Any] else {
            throw Failure(code: "usage_storage")
        }
        return object
    }

    // V2 keys bind a token to both an account and organization. Never fall back
    // to a token from another account, even if it has a longer lifetime.
    static func matchingToken(_ cache: [String: Any], account: String, organization: String,
                              now: TimeInterval) -> String? {
        let pattern = "^acct:([0-9A-Fa-f-]+)\\|([^:]+):([0-9A-Fa-f-]+):https://api\\.anthropic\\.com:(.+)$"
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        var candidates: [(String, Int, Double)] = []
        for (name, raw) in cache {
            let range = NSRange(name.startIndex..<name.endIndex, in: name)
            guard let match = regex.firstMatch(in: name, range: range),
                  let a = Range(match.range(at: 1), in: name),
                  let o = Range(match.range(at: 3), in: name),
                  let s = Range(match.range(at: 4), in: name),
                  name[a].lowercased() == account.lowercased(),
                  name[o].lowercased() == organization.lowercased(),
                  let entry = raw as? [String: Any],
                  let token = entry["token"] as? String, !token.isEmpty,
                  let expires = entry["expiresAt"] as? NSNumber,
                  CFGetTypeID(expires) != CFBooleanGetTypeID() else { continue }
            let scopes = name[s].split(whereSeparator: { $0.isWhitespace }).map(String.init)
            let expiry = expires.doubleValue > 100_000_000_000 ? expires.doubleValue / 1000 : expires.doubleValue
            guard scopes.contains("user:profile"), expiry.isFinite, expiry > now + 60 else { continue }
            candidates.append((token, scopes.count, expiry))
        }
        return candidates.sorted { left, right in
            left.1 == right.1 ? left.2 > right.2 : left.1 < right.1
        }.first?.0
    }

    static func parseUsage(_ data: Data, now: TimeInterval) -> [String: Any]? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        var result: [String: Any] = ["observed_at": now]
        for name in ["five_hour", "seven_day"] {
            guard let window = object[name] as? [String: Any],
                  let value = window["utilization"] as? NSNumber,
                  CFGetTypeID(value) != CFBooleanGetTypeID() else { continue }
            let percent = value.doubleValue
            guard percent.isFinite, (0...100).contains(percent) else { continue }
            if let raw = window["resets_at"] as? String {
                let formatter = ISO8601DateFormatter()
                formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                var date = formatter.date(from: raw)
                if date == nil {
                    formatter.formatOptions = [.withInternetDateTime]
                    date = formatter.date(from: raw)
                }
                if let reset = date?.timeIntervalSince1970 {
                    if reset <= now { continue }
                    result[name + "_reset_at"] = reset
                }
            }
            result[name] = percent
        }
        return result["five_hour"] != nil || result["seven_day"] != nil ? result : nil
    }

    private static func safeStoragePassword(allowPrompt: Bool) throws -> Data {
        let context = LAContext()
        context.interactionNotAllowed = !allowPrompt
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "Claude Safe Storage",
            kSecAttrAccount as String: "Claude Key",
            kSecMatchLimit as String: kSecMatchLimitOne,
            kSecReturnData as String: true,
            kSecUseAuthenticationContext as String: context,
        ]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data, !data.isEmpty else {
            if status == errSecUserCanceled || status == errSecAuthFailed || status == errSecInteractionNotAllowed {
                throw Failure(code: "usage_keychain")
            }
            throw Failure(code: "usage_storage")
        }
        return data
    }

    private static func readConfig(_ path: String, expectedAccount: String) throws -> [String: Any] {
        let fd = open(path, O_RDONLY | O_NOFOLLOW)
        guard fd >= 0 else { throw Failure(code: "usage_storage") }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        var info = stat()
        guard fstat(fd, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG,
              info.st_size <= 8 * 1024 * 1024,
              let data = try? handle.readToEnd(), let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let account = object["lastKnownAccountUuid"] as? String,
              account.lowercased() == expectedAccount.lowercased() else { throw Failure(code: "usage_storage") }
        return object
    }

    private static func fetchUsage(token: String) throws -> Data {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = 12
        let session = URLSession(configuration: configuration, delegate: NoRedirect(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        var request = URLRequest(url: URL(string: "https://api.anthropic.com/api/oauth/usage")!)
        request.httpMethod = "GET"
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        request.setValue("oauth-2025-04-20", forHTTPHeaderField: "anthropic-beta")
        request.setValue("Claude-Account-Switcher/0.4.1", forHTTPHeaderField: "User-Agent")
        let done = DispatchSemaphore(value: 0)
        var responseData: Data?
        var response: HTTPURLResponse?
        session.dataTask(with: request) { data, received, _ in
            responseData = data
            response = received as? HTTPURLResponse
            done.signal()
        }.resume()
        guard done.wait(timeout: .now() + 15) == .success, let http = response else {
            throw Failure(code: "usage_unavailable")
        }
        if http.statusCode == 429 {
            let seconds = Int(http.value(forHTTPHeaderField: "Retry-After") ?? "") ?? 0
            throw Failure(code: "usage_limited", retrySeconds: min(max(seconds, 900), 86400))
        }
        if http.statusCode == 401 || http.statusCode == 403 { throw Failure(code: "usage_expired") }
        guard (200...299).contains(http.statusCode), let data = responseData, data.count <= 1_000_000 else {
            throw Failure(code: "usage_unavailable")
        }
        return data
    }

    static func run() {
        do {
            let input = FileHandle.standardInput.readDataToEndOfFile()
            guard input.count <= 16_384,
                  let args = try? JSONSerialization.jsonObject(with: input) as? [String: Any],
                  let profile = args["profile"] as? String,
                  let account = args["account"] as? String,
                  let organization = args["organization"] as? String else { throw Failure(code: "usage_storage") }
            let config = try readConfig(profile + "/config.json", expectedAccount: account)
            guard let encoded = config["oauth:tokenCacheV2"] as? String else { throw Failure(code: "usage_storage") }
            var password = try safeStoragePassword(allowPrompt: args["allow_prompt"] as? Bool == true)
            defer { password.resetBytes(in: 0..<password.count) }
            let cache = try decryptCache(encoded, password: password)
            guard let token = matchingToken(cache, account: account, organization: organization,
                                            now: Date().timeIntervalSince1970) else { throw Failure(code: "usage_expired") }
            let data = try fetchUsage(token: token)
            guard let result = parseUsage(data, now: Date().timeIntervalSince1970) else {
                throw Failure(code: "usage_unavailable")
            }
            write(["ok": true, "usage": result])
        } catch let error as Failure {
            var output: [String: Any] = ["ok": false, "error_code": error.code]
            if let delay = error.retrySeconds { output["retry_seconds"] = delay }
            write(output)
        } catch {
            write(["ok": false, "error_code": "usage_unavailable"])
        }
    }

    private static func write(_ output: [String: Any]) {
        if let data = try? JSONSerialization.data(withJSONObject: output) {
            FileHandle.standardOutput.write(data)
        }
    }
}
