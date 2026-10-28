// Hallmark · cockpit interface · dark graphite, cool cyan and restrained amber.
// Pre-emit critique: philosophy 5, hierarchy 5, execution 4, specificity 5, restraint 4, variety 4.
import AppKit
import Combine
import Foundation
import SwiftUI

private enum Cockpit {
    static let background = Color(red: 0.035, green: 0.049, blue: 0.068)
    static let surface = Color(red: 0.060, green: 0.081, blue: 0.105)
    static let surfaceRaised = Color(red: 0.078, green: 0.108, blue: 0.134)
    static let outline = Color(red: 0.180, green: 0.266, blue: 0.302)
    static let ink = Color(red: 0.913, green: 0.954, blue: 0.950)
    static let muted = Color(red: 0.573, green: 0.669, blue: 0.684)
    static let dim = Color(red: 0.381, green: 0.482, blue: 0.511)
    static let cyan = Color(red: 0.474, green: 0.901, blue: 0.898)
    static let amber = Color(red: 0.969, green: 0.628, blue: 0.406)
    static let actionInk = Color(red: 0.035, green: 0.098, blue: 0.113)
    static let grid = Color(red: 0.196, green: 0.314, blue: 0.350)
}

private struct Profile: Identifiable {
    let id: String
    let configured: Bool
    let usage: UsageSnapshot?
}

private struct UsageSnapshot {
    let fiveHour: Double?
    let sevenDay: Double?
    let observedAt: Date
    let stale: Bool
}

private final class AccountModel: ObservableObject {
    @Published var strings: [String: String] = [:]
    @Published var language: String
    @Published var profiles: [Profile] = []
    @Published var selectedID = ""
    @Published var active = "none"
    @Published var problemCode: String?
    @Published var isBusy = false

    private let script = NSHomeDirectory() + "/Library/Application Support/Local Claude Accounts/manager.py"
    private var translations: [String: [String: String]] = [:]
    private var isPolling = false
    private var timer: Timer?
    private var preferredSelection: String?
    private let preferenceKey = "interfaceLanguage"
    let languages: [(String, String)] = [
        ("en", "English"), ("zh", "简体中文"), ("ja", "日本語"), ("ko", "한국어"),
        ("es", "Español"), ("fr", "Français"), ("de", "Deutsch")
    ]

    init() {
        language = UserDefaults.standard.string(forKey: "interfaceLanguage") ?? "system"
        if let url = Bundle.main.url(forResource: "translations", withExtension: "json"),
           let data = try? Data(contentsOf: url),
           let all = (try? JSONSerialization.jsonObject(with: data)) as? [String: [String: String]] {
            translations = all
        }
        applyLanguage()
    }

    func start() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refresh() }
    }

    func t(_ key: String) -> String { strings[key] ?? translations["en"]?[key] ?? key }

    var languageName: String {
        if language == "system" { return t("system_language") }
        return languages.first(where: { $0.0 == language })?.1 ?? t("system_language")
    }

    func setLanguage(_ code: String) {
        guard code == "system" || languages.contains(where: { $0.0 == code }) else { return }
        language = code
        UserDefaults.standard.set(code, forKey: preferenceKey)
        applyLanguage()
    }

    private func applyLanguage() {
        let preferred = String((Locale.preferredLanguages.first ?? "en").prefix(2)).lowercased()
        let key = language == "system" ? preferred : language
        strings = translations[key] ?? translations["en"] ?? [:]
    }

    var statusText: String {
        if isBusy { return t("working") }
        switch active {
        case "none": return t("none")
        case "many": return t("many")
        case "unknown": return t("unknown")
        default: return String(format: t("current"), active.uppercased())
        }
    }

    var selectedProfile: Profile? { profiles.first(where: { $0.id == selectedID }) }
    var selectedUsage: UsageSnapshot? { selectedProfile?.usage }
    var usageUpdated: String {
        guard let usage = selectedUsage else { return t("usage_missing") }
        let formatter = DateFormatter()
        formatter.dateStyle = .short
        formatter.timeStyle = .short
        if language != "system" { formatter.locale = Locale(identifier: language) }
        let time = formatter.string(from: usage.observedAt)
        return String(format: t(usage.stale ? "usage_stale" : "usage_updated"), time)
    }
    var selectedState: String {
        guard let profile = selectedProfile else { return t("inactive_state") }
        if profile.id == active { return t("active_state") }
        return t(profile.configured ? "ready_state" : "pending_state")
    }

    private func invoke(_ args: [String]) -> [String: Any] {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        process.arguments = [script] + args
        let output = Pipe()
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            return (try JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? ["ok": false]
        } catch {
            return ["ok": false]
        }
    }

    private func apply(_ result: [String: Any]) {
        guard result["ok"] as? Bool == true else {
            active = "unknown"
            problemCode = "error_generic"
            return
        }
        active = result["active"] as? String ?? "unknown"
        problemCode = result["problem_code"] as? String
        let entries = result["profiles"] as? [[String: Any]] ?? []
        profiles = entries.compactMap { entry in
            guard let id = entry["id"] as? String else { return nil }
            var usage: UsageSnapshot?
            if let data = entry["usage"] as? [String: Any],
               let observed = (data["observed_at"] as? NSNumber)?.doubleValue {
                usage = UsageSnapshot(fiveHour: (data["five_hour"] as? NSNumber)?.doubleValue,
                                      sevenDay: (data["seven_day"] as? NSNumber)?.doubleValue,
                                      observedAt: Date(timeIntervalSince1970: observed),
                                      stale: data["stale"] as? Bool ?? true)
            }
            return Profile(id: id, configured: entry["configured"] as? Bool ?? false, usage: usage)
        }
        let candidate = preferredSelection ?? selectedID
        if profiles.contains(where: { $0.id == candidate }) {
            selectedID = candidate
        } else if profiles.contains(where: { $0.id == active }) {
            selectedID = active
        } else {
            selectedID = profiles.first?.id ?? ""
        }
        preferredSelection = nil
    }

    func refresh() {
        guard !isBusy, !isPolling else { return }
        isPolling = true
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self = self else { return }
            let result = self.invoke(["status"])
            DispatchQueue.main.async {
                self.isPolling = false
                guard !self.isBusy else { return }
                self.apply(result)
            }
        }
    }

    private func alert(title: String, message: String) {
        let dialog = NSAlert()
        dialog.messageText = title
        dialog.informativeText = message
        dialog.addButton(withTitle: t("ok"))
        dialog.runModal()
    }

    private func confirm(_ result: [String: Any], target: String?) -> Bool {
        let current = result["active"] as? String ?? "unknown"
        if current == "many" || current == "unknown" {
            alert(title: t("error_title"), message: t("error_multiple"))
            return false
        }
        if current == "none" || current == target { return true }
        let dialog = NSAlert()
        dialog.messageText = t("warning_title")
        dialog.informativeText = t("warning_body")
        dialog.alertStyle = .warning
        dialog.addButton(withTitle: t("continue"))
        dialog.addButton(withTitle: t("cancel"))
        return dialog.runModal() == .alertFirstButtonReturn
    }

    func switchSelected() {
        guard !isBusy, !selectedID.isEmpty else { return }
        begin(target: selectedID, adding: false)
    }

    func addAccount() {
        guard !isBusy else { return }
        begin(target: nil, adding: true)
    }

    private func begin(target: String?, adding: Bool) {
        isBusy = true
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self = self else { return }
            let current = self.invoke(["status"])
            DispatchQueue.main.async {
                guard current["ok"] as? Bool == true else {
                    self.isBusy = false
                    self.alert(title: self.t("error_title"), message: self.t("error_generic"))
                    return
                }
                guard self.confirm(current, target: target) else {
                    self.isBusy = false
                    self.apply(current)
                    return
                }
                DispatchQueue.global(qos: .userInitiated).async {
                    var chosen = target
                    var result: [String: Any] = [:]
                    if adding {
                        result = self.invoke(["add"])
                        chosen = result["target"] as? String
                    }
                    if let chosen = chosen, !adding || result["ok"] as? Bool == true {
                        result = self.invoke(["switch", chosen, "--allow-quit"])
                    }
                    let latest = self.invoke(["status"])
                    DispatchQueue.main.async {
                        self.preferredSelection = chosen
                        self.isBusy = false
                        self.apply(latest)
                        if result["ok"] as? Bool != true {
                            let code = result["error_code"] as? String ?? "error_generic"
                            self.alert(title: self.t("error_title"), message: self.t(code))
                        } else if result["needs_login"] as? Bool == true {
                            self.alert(title: self.t("title"), message: self.t("first_login"))
                        } else if result["issues"] as? Bool == true {
                            self.alert(title: self.t("title"), message: self.t("sync_notice"))
                        }
                    }
                }
            }
        }
    }
}

private struct GridField: View {
    var body: some View {
        Canvas { context, size in
            var lines = Path()
            stride(from: 0.0, through: size.width, by: 32).forEach { x in
                lines.move(to: CGPoint(x: x, y: 0)); lines.addLine(to: CGPoint(x: x, y: size.height))
            }
            stride(from: 0.0, through: size.height, by: 32).forEach { y in
                lines.move(to: CGPoint(x: 0, y: y)); lines.addLine(to: CGPoint(x: size.width, y: y))
            }
            context.stroke(lines, with: .color(Cockpit.grid.opacity(0.06)), lineWidth: 0.5)
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

private struct UsageMetric: View {
    let title: String
    let value: Double?
    let stale: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text(title).font(.system(size: 11, weight: .medium)).foregroundColor(Cockpit.muted)
                Spacer(minLength: 4)
                Text(value.map { String(format: "%.0f%%", $0) } ?? "—")
                    .font(.system(size: 13, weight: .semibold, design: .monospaced))
                    .foregroundColor(value == nil ? Cockpit.dim : Cockpit.ink)
            }
            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    Capsule().fill(Cockpit.outline.opacity(0.55))
                    if let value = value {
                        Capsule().fill(value >= 90 ? Cockpit.amber : Cockpit.cyan)
                            .opacity(stale ? 0.58 : 0.9)
                            .frame(width: geometry.size.width * min(max(value, 0), 100) / 100)
                    }
                }
            }
            .frame(height: 5)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(title): \(value.map { String(format: "%.0f%%", $0) } ?? "—")")
    }
}

private struct Panel<Content: View>: View {
    let content: Content
    init(@ViewBuilder content: () -> Content) { self.content = content() }
    var body: some View {
        content
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(LinearGradient(colors: [Cockpit.surfaceRaised.opacity(0.80), Cockpit.surface.opacity(0.94)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
            )
            .overlay(RoundedRectangle(cornerRadius: 12).stroke(Cockpit.outline.opacity(0.75), lineWidth: 1))
    }
}

private struct ProfileRow: View {
    let profile: Profile
    let selected: Bool
    let active: Bool
    let accountLabel: String
    let state: String
    let action: () -> Void
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 11) {
                Text(profile.id.uppercased())
                    .font(.system(size: 15, weight: .semibold, design: .monospaced))
                    .foregroundColor(selected ? Cockpit.cyan : Cockpit.ink)
                    .frame(width: 36, height: 36)
                    .background(RoundedRectangle(cornerRadius: 7).fill(Cockpit.background.opacity(0.72)))
                    .overlay(RoundedRectangle(cornerRadius: 7).stroke(Cockpit.outline.opacity(0.7), lineWidth: 1))
                VStack(alignment: .leading, spacing: 3) {
                    Text(accountLabel + " " + profile.id.uppercased())
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(Cockpit.ink).lineLimit(1)
                    Text(state)
                        .font(.system(size: 10, weight: .medium))
                        .foregroundColor(active ? Cockpit.cyan : Cockpit.muted).lineLimit(1)
                }
                Spacer(minLength: 4)
                if active { Circle().fill(Cockpit.cyan).frame(width: 5, height: 5) }
            }
            .padding(.horizontal, 10).padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 9).fill(selected ? Cockpit.cyan.opacity(0.11) : (hovering ? Cockpit.ink.opacity(0.04) : Color.clear)))
            .overlay(RoundedRectangle(cornerRadius: 9).stroke(selected ? Cockpit.cyan.opacity(0.48) : Color.clear, lineWidth: 1))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .accessibilityLabel("\(accountLabel) \(profile.id.uppercased()), \(state)")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

private struct PrimaryControl: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .bold))
            .foregroundColor(Cockpit.actionInk)
            .padding(.horizontal, 18).frame(height: 42)
            .background(RoundedRectangle(cornerRadius: 8).fill(Cockpit.cyan.opacity(configuration.isPressed ? 0.78 : 1)))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Cockpit.ink.opacity(0.25), lineWidth: 1))
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
    }
}

private struct CockpitView: View {
    @ObservedObject var model: AccountModel

    private var statusColor: Color {
        (model.active != "none" && model.active != "many" && model.active != "unknown") ? Cockpit.cyan : Cockpit.amber
    }

    var body: some View {
        ZStack {
            Cockpit.background
            RadialGradient(colors: [Cockpit.cyan.opacity(0.10), .clear], center: .topTrailing,
                           startRadius: 0, endRadius: 610)
            GridField()
            VStack(spacing: 0) {
                header
                Rectangle().fill(Cockpit.outline.opacity(0.68)).frame(height: 1)
                HStack(spacing: 16) {
                    accountPanel.frame(width: 222)
                    selectedPanel.frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                .padding(.vertical, 17)
                footer
            }
            .padding(.horizontal, 28)
            .padding(.top, 35)
            .padding(.bottom, 21)
        }
        .frame(minWidth: 760, minHeight: 520)
        .preferredColorScheme(.dark)
    }

    private var header: some View {
        HStack(alignment: .center, spacing: 12) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable().interpolation(.high).frame(width: 36, height: 36)
                .clipShape(RoundedRectangle(cornerRadius: 9))
            VStack(alignment: .leading, spacing: 3) {
                Text("CLAUDE")
                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                    .tracking(2.0).foregroundColor(Cockpit.cyan)
                Text(model.t("title"))
                    .font(.system(size: 17, weight: .semibold)).foregroundColor(Cockpit.ink)
            }
            Spacer(minLength: 15)
            HStack(spacing: 7) {
                Circle().fill(statusColor).frame(width: 6, height: 6)
                Text(model.statusText).font(.system(size: 11, weight: .medium)).lineLimit(1)
            }
            .foregroundColor(Cockpit.ink)
            .padding(.horizontal, 11).padding(.vertical, 8)
            .background(Capsule().fill(Cockpit.surfaceRaised.opacity(0.8)))
            .overlay(Capsule().stroke(Cockpit.outline.opacity(0.65), lineWidth: 1))
            languageMenu
        }
        .padding(.bottom, 17)
    }

    private var languageMenu: some View {
        Menu {
            Button(model.t("system_language")) { model.setLanguage("system") }
            Divider()
            ForEach(model.languages, id: \.0) { code, name in
                Button(name) { model.setLanguage(code) }
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "globe")
                Text(model.languageName).lineLimit(1)
                Image(systemName: "chevron.down").font(.system(size: 9, weight: .bold))
            }
            .font(.system(size: 11, weight: .medium)).foregroundColor(Cockpit.muted)
            .padding(.horizontal, 9).frame(height: 32)
            .background(RoundedRectangle(cornerRadius: 7).fill(Cockpit.surface.opacity(0.65)))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(Cockpit.outline.opacity(0.6), lineWidth: 1))
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .accessibilityLabel(model.t("language"))
    }

    private var accountPanel: some View {
        Panel {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text(model.t("profiles"))
                        .font(.system(size: 13, weight: .semibold)).foregroundColor(Cockpit.ink)
                    Spacer()
                }
                .padding(.horizontal, 14).padding(.top, 16)
                Rectangle().fill(Cockpit.outline.opacity(0.55)).frame(height: 1)
                ScrollView {
                    VStack(spacing: 5) {
                        ForEach(model.profiles) { profile in
                            let isActive = profile.id == model.active
                            ProfileRow(profile: profile, selected: profile.id == model.selectedID,
                                       active: isActive, accountLabel: model.t("account"),
                                       state: model.t(isActive ? "active_state" : (profile.configured ? "ready_state" : "pending_state"))) {
                                model.selectedID = profile.id
                            }
                            .disabled(model.isBusy)
                        }
                    }.padding(.horizontal, 8)
                }
                Spacer(minLength: 0)
                Button(action: model.addAccount) {
                    HStack(spacing: 8) {
                        Image(systemName: "plus")
                        Text(model.t("add")).lineLimit(1)
                        Spacer()
                    }
                    .font(.system(size: 12, weight: .semibold)).foregroundColor(Cockpit.ink)
                    .padding(.horizontal, 12).frame(height: 40)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Cockpit.surfaceRaised))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Cockpit.outline, lineWidth: 1))
                }
                .buttonStyle(.plain).disabled(model.isBusy)
                .padding(.horizontal, 12).padding(.bottom, 13)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    private var selectedPanel: some View {
        Panel {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 7) {
                    Rectangle().fill(Cockpit.cyan).frame(width: 14, height: 2)
                    Text(model.t("selected_profile"))
                        .font(.system(size: 11, weight: .medium)).foregroundColor(Cockpit.muted)
                }
                HStack(alignment: .bottom, spacing: 16) {
                    VStack(alignment: .leading, spacing: 9) {
                        Text(model.selectedID.isEmpty ? model.t("choose_hint") : model.t("account") + " " + model.selectedID.uppercased())
                            .font(.system(size: 31, weight: .semibold)).foregroundColor(Cockpit.ink)
                            .lineLimit(1).minimumScaleFactor(0.75)
                        HStack(spacing: 7) {
                            Circle().fill(model.selectedID == model.active ? Cockpit.cyan : Cockpit.amber).frame(width: 5, height: 5)
                            Text(model.selectedState).font(.system(size: 11, weight: .semibold, design: .monospaced))
                                .tracking(0.6).foregroundColor(Cockpit.muted).lineLimit(1)
                        }
                    }
                    Spacer(minLength: 8)
                    Button(action: model.switchSelected) {
                        HStack(spacing: 10) {
                            Text(model.selectedID == model.active ? model.t("active_state") : model.t("switch_action"))
                                .lineLimit(1)
                            Image(systemName: model.selectedID == model.active ? "checkmark" : "arrow.right")
                        }
                    }
                    .buttonStyle(PrimaryControl())
                    .disabled(model.isBusy || model.selectedID.isEmpty || model.selectedID == model.active)
                    .opacity(model.selectedID == model.active ? 0.50 : 1)
                }
                .padding(.top, 26)
                Rectangle().fill(Cockpit.outline.opacity(0.60)).frame(height: 1).padding(.vertical, 26)
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(model.t("usage_label"))
                        .font(.system(size: 12, weight: .semibold)).foregroundColor(Cockpit.ink)
                    Spacer(minLength: 6)
                    Text(model.usageUpdated)
                        .font(.system(size: 10, weight: .medium))
                        .foregroundColor(model.selectedUsage?.stale == true ? Cockpit.amber : Cockpit.muted)
                        .lineLimit(1).minimumScaleFactor(0.75)
                }
                VStack(spacing: 18) {
                    UsageMetric(title: model.t("five_hour_label"), value: model.selectedUsage?.fiveHour,
                                stale: model.selectedUsage?.stale ?? false)
                    UsageMetric(title: model.t("seven_day_label"), value: model.selectedUsage?.sevenDay,
                                stale: model.selectedUsage?.stale ?? false)
                }
                .padding(.top, 18)
                Spacer(minLength: 0)
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    private var footer: some View {
        HStack(spacing: 8) {
            Rectangle().fill(Cockpit.amber.opacity(0.8)).frame(width: 13, height: 2)
            if let problem = model.problemCode {
                Text(model.t(problem)).foregroundColor(Cockpit.amber).lineLimit(1)
            } else {
                Text(model.t("local_note")).foregroundColor(Cockpit.muted).lineLimit(1)
            }
            Spacer()
        }
        .font(.system(size: 10, weight: .medium, design: .monospaced))
        .tracking(0.5)
    }
}

private final class AppDelegate: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private let model = AccountModel()
    private var languageObserver: AnyCancellable?

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 550),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                          backing: .buffered, defer: false)
        window.title = model.t("title")
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.backgroundColor = NSColor(red: 0.035, green: 0.049, blue: 0.068, alpha: 1)
        window.appearance = NSAppearance(named: .darkAqua)
        window.minSize = NSSize(width: 760, height: 520)
        window.contentView = NSHostingView(rootView: CockpitView(model: model))
        languageObserver = model.$strings.receive(on: RunLoop.main).sink { [weak self] strings in
            self?.window.title = strings["title"] ?? "Claude Account Switcher"
        }
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        model.start()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

let app = NSApplication.shared
private let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
