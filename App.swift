import AppKit
import Foundation

final class AccountWindow: NSObject, NSApplicationDelegate {
    private var window: NSWindow!
    private let statusLabel = NSTextField(wrappingLabelWithString: "")
    private let subtitle = NSTextField(wrappingLabelWithString: "")
    private let accounts = NSPopUpButton()
    private let switchButton = NSButton()
    private let addButton = NSButton()
    private var updating = false
    private var cached: [String: Any] = [:]
    private var timer: Timer?
    private var preferredSelection: String?
    private let script = NSHomeDirectory() + "/Library/Application Support/Local Claude Accounts/manager.py"
    private var strings: [String: String] = [:]

    private func loadStrings() {
        guard let url = Bundle.main.url(forResource: "translations", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let all = (try? JSONSerialization.jsonObject(with: data)) as? [String: [String: String]] else { return }
        let prefix = String((Locale.preferredLanguages.first ?? "en").prefix(2)).lowercased()
        strings = all[prefix] ?? all["en"] ?? [:]
    }
    private func t(_ key: String) -> String { strings[key] ?? key }

    func applicationDidFinishLaunching(_ notification: Notification) {
        loadStrings()
        let view = NSView(frame: NSRect(x: 0, y: 0, width: 500, height: 270))
        window = NSWindow(contentRect: view.frame, styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = t("title"); window.contentView = view; window.center()
        let title = NSTextField(labelWithString: t("title"))
        title.font = NSFont.systemFont(ofSize: 22, weight: .semibold)
        subtitle.stringValue = t("subtitle"); subtitle.font = NSFont.systemFont(ofSize: 13)
        subtitle.textColor = .secondaryLabelColor
        statusLabel.stringValue = t("checking"); statusLabel.font = NSFont.systemFont(ofSize: 14, weight: .medium)
        accounts.bezelStyle = .rounded
        switchButton.title = t("switch"); switchButton.bezelStyle = .rounded
        switchButton.target = self; switchButton.action = #selector(switchSelected)
        addButton.title = t("add"); addButton.bezelStyle = .rounded
        addButton.target = self; addButton.action = #selector(addAccount)
        let controls = NSStackView(views: [accounts, switchButton, addButton])
        controls.orientation = .horizontal; controls.spacing = 12
        let stack = NSStackView(views: [title, subtitle, statusLabel, controls])
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 20
        stack.translatesAutoresizingMaskIntoConstraints = false; view.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -28),
            stack.topAnchor.constraint(equalTo: view.topAnchor, constant: 26),
            subtitle.widthAnchor.constraint(equalTo: stack.widthAnchor),
            statusLabel.widthAnchor.constraint(equalTo: stack.widthAnchor),
            controls.widthAnchor.constraint(equalTo: stack.widthAnchor),
            accounts.widthAnchor.constraint(greaterThanOrEqualToConstant: 130),
            switchButton.heightAnchor.constraint(equalToConstant: 34),
            addButton.heightAnchor.constraint(equalToConstant: 34)
        ])
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.refresh() }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    private func invoke(_ args: [String]) -> [String: Any] {
        let proc = Process(); proc.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        proc.arguments = [script] + args
        let pipe = Pipe(); proc.standardOutput = pipe; proc.standardError = FileHandle.nullDevice
        do {
            try proc.run(); let bytes = pipe.fileHandleForReading.readDataToEndOfFile(); proc.waitUntilExit()
            return (try JSONSerialization.jsonObject(with: bytes) as? [String: Any]) ?? ["ok": false]
        } catch { return ["ok": false] }
    }
    private func showAlert(title: String, message: String) {
        let alert = NSAlert(); alert.messageText = title; alert.informativeText = message
        alert.addButton(withTitle: t("ok")); alert.runModal()
    }
    private func render(_ result: [String: Any]) {
        cached = result
        guard result["ok"] as? Bool == true else { statusLabel.stringValue = t("error_generic"); return }
        let active = result["active"] as? String ?? "unknown"
        switch active {
        case "none": statusLabel.stringValue = t("none")
        case "many": statusLabel.stringValue = t("many")
        case "unknown": statusLabel.stringValue = t("unknown")
        default: statusLabel.stringValue = String(format: t("current"), active.uppercased())
        }
        if let problem = result["problem_code"] as? String {
            statusLabel.stringValue += "\n" + t(problem)
        }
        let profiles = result["profiles"] as? [[String: Any]] ?? []
        let ids = profiles.compactMap { $0["id"] as? String }
        let shown = accounts.itemArray.compactMap { $0.representedObject as? String }
        if ids != shown {
            let previous = preferredSelection ?? (accounts.selectedItem?.representedObject as? String) ?? active
            accounts.removeAllItems()
            for id in ids {
                accounts.addItem(withTitle: t("account") + " " + id.uppercased())
                accounts.lastItem?.representedObject = id
            }
            if let index = ids.firstIndex(of: previous) { accounts.selectItem(at: index) }
            preferredSelection = nil
        }
    }
    private func setBusy(_ busy: Bool) {
        updating = busy; accounts.isEnabled = !busy; switchButton.isEnabled = !busy; addButton.isEnabled = !busy
    }
    private func refresh() {
        guard !updating else { return }; updating = true
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self = self else { return }; let result = self.invoke(["status"])
            DispatchQueue.main.async { self.updating = false; self.render(result) }
        }
    }
    private func confirm(_ status: [String: Any], target: String?) -> Bool {
        let active = status["active"] as? String ?? "unknown"
        if active == "many" || active == "unknown" {
            showAlert(title: t("error_title"), message: t("error_multiple"))
            return false
        }
        if active == "none" || active == target { return true }
        let alert = NSAlert(); alert.messageText = t("warning_title"); alert.informativeText = t("warning_body")
        alert.alertStyle = .warning; alert.addButton(withTitle: t("continue")); alert.addButton(withTitle: t("cancel"))
        return alert.runModal() == .alertFirstButtonReturn
    }
    @objc private func switchSelected() {
        guard !updating, let target = accounts.selectedItem?.representedObject as? String else { return }
        begin(target: target, adding: false)
    }
    @objc private func addAccount() { guard !updating else { return }; begin(target: nil, adding: true) }

    private func begin(target: String?, adding: Bool) {
        setBusy(true)
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self = self else { return }; let status = self.invoke(["status"])
            DispatchQueue.main.async {
                guard status["ok"] as? Bool == true else {
                    self.setBusy(false); self.showAlert(title: self.t("error_title"), message: self.t("error_generic")); return
                }
                guard self.confirm(status, target: target) else { self.setBusy(false); self.render(status); return }
                self.statusLabel.stringValue = self.t("working")
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
                        self.setBusy(false); self.render(latest)
                        if result["ok"] as? Bool != true {
                            let key = result["error_code"] as? String ?? "error_generic"
                            self.showAlert(title: self.t("error_title"), message: self.t(key))
                        } else if result["needs_login"] as? Bool == true {
                            self.showAlert(title: self.t("title"), message: self.t("first_login"))
                        } else if result["issues"] as? Bool == true {
                            self.showAlert(title: self.t("title"), message: self.t("sync_notice"))
                        }
                    }
                }
            }
        }
    }
}

let app = NSApplication.shared
let delegate = AccountWindow(); app.delegate = delegate
app.setActivationPolicy(.regular); app.run()
