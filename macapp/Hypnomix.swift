// Hypnomix.app: a window around the local hypnomix app (`hypnomix app`). No network beyond this computer.
// Build: ./build.sh   (needs the Swift compiler from Xcode's command line tools)
import Cocoa
import WebKit

let port = 8791
let home = URL(string: "http://127.0.0.1:\(port)/")!

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var tries = 0

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        web.uiDelegate = self
        web.navigationDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1040, height: 800),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "hypnomix"
        window.contentView = web
        window.center()
        window.setFrameAutosaveName("HypnomixMain")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        message("Starting hypnomix…")
        isUp { up in
            if up { self.web.load(URLRequest(url: home)) } else { self.startServer() }
        }
    }

    // ---- the server
    // the installer's copy: Python, hypnomix and ffmpeg inside the app (packaging/mac/build_dmg.sh)
    var bundled: String? {
        guard let res = Bundle.main.resourcePath else { return nil }
        let py = "\(res)/python/bin/python3"
        return FileManager.default.isExecutableFile(atPath: py) ? py : nil
    }

    func pythonPath() -> String? {
        if let b = bundled { return b }
        var candidates: [String] = []
        if let saved = UserDefaults.standard.string(forKey: "HypnomixPython") { candidates.append(saved) }
        if let baked = Bundle.main.object(forInfoDictionaryKey: "HypnomixPython") as? String, !baked.isEmpty { candidates.append(baked) }
        let h = NSHomeDirectory()
        candidates += ["\(h)/hypnomix/.venv/bin/python", "\(h)/Documents/hypnomix/.venv/bin/python", "\(h)/Developer/hypnomix/.venv/bin/python"]
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    func startServer() {
        guard let py = pythonPath() else { askForFolder(); return }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: py)
        p.arguments = ["-m", "hypnomix.cli", "app", "--no-open", "--port", "\(port)"]
        p.environment = serverEnv()
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch {
            message("Could not start hypnomix: \(error.localizedDescription)")
            return
        }
        server = p
        waitForServer()
    }

    func serverEnv() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        var path = "/opt/homebrew/bin:/usr/local/bin:" + (env["PATH"] ?? "/usr/bin:/bin")   // ffmpeg, rubberband
        if bundled != nil, let res = Bundle.main.resourcePath {
            path = "\(res)/bin:" + path                   // the bundled ffmpeg first
            env["PYTHONDONTWRITEBYTECODE"] = "1"          // compiled at build time; never write inside the signed app
            env["PYTHONNOUSERSITE"] = "1"                 // the user's own pip packages stay out of it
        }
        env["PATH"] = path
        return env
    }

    func waitForServer() {
        tries += 1
        isUp { up in
            if up { self.web.load(URLRequest(url: home)); return }
            if self.tries > 60 || self.server?.isRunning == false {
                self.message(self.bundled != nil
                    ? "hypnomix did not start. Quit and open it again; if it still fails, download the installer again from hypnomix.bradfieldenterprises.org."
                    : "hypnomix did not start. In Terminal, run: hypnomix app   and read what it says.")
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { self.waitForServer() }
        }
    }

    func isUp(_ done: @escaping (Bool) -> Void) {
        var req = URLRequest(url: home.appendingPathComponent("api/state"))
        req.timeoutInterval = 1
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async { done(ok) }
        }.resume()
    }

    func askForFolder() {
        let a = NSAlert()
        a.messageText = "Where is hypnomix installed?"
        a.informativeText = "Choose the hypnomix folder (the one you cloned or unzipped, after running the install steps in it)."
        a.addButton(withTitle: "Choose folder…")
        a.addButton(withTitle: "Quit")
        if a.runModal() != .alertFirstButtonReturn { NSApp.terminate(nil); return }
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        if panel.runModal() == .OK, let dir = panel.url {
            let py = dir.appendingPathComponent(".venv/bin/python").path
            if FileManager.default.isExecutableFile(atPath: py) {
                UserDefaults.standard.set(py, forKey: "HypnomixPython")
                startServer()
                return
            }
            message("No .venv/bin/python in that folder. Run the install steps there first (uv venv && uv pip install -e .).")
        } else { NSApp.terminate(nil) }
    }

    func message(_ text: String) {
        let safe = text.replacingOccurrences(of: "<", with: "&lt;")
        web.loadHTMLString("<body style='font:16px system-ui;padding:40px;color:#555'>\(safe)</body>", baseURL: nil)
    }

    func applicationWillTerminate(_ note: Notification) { server?.terminate() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    // ---- the page's alert() and confirm()
    func webView(_ w: WKWebView, runJavaScriptAlertPanelWithMessage msg: String, initiatedByFrame f: WKFrameInfo, completionHandler done: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = msg; a.runModal(); done()
    }
    func webView(_ w: WKWebView, runJavaScriptConfirmPanelWithMessage msg: String, initiatedByFrame f: WKFrameInfo, completionHandler done: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = msg
        a.addButton(withTitle: "OK"); a.addButton(withTitle: "Cancel")
        done(a.runModal() == .alertFirstButtonReturn)
    }
    // links with target=_blank (the setup's "get a key" links): the browser, not a new window
    func webView(_ w: WKWebView, createWebViewWith c: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures f: WKWindowFeatures) -> WKWebView? {
        if let u = action.request.url { NSWorkspace.shared.open(u) }
        return nil
    }
    // links that leave the app open in the browser
    func webView(_ w: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let u = action.request.url, let host = u.host, host != "127.0.0.1", action.navigationType == .linkActivated {
            NSWorkspace.shared.open(u); decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }

    @objc func reload() { web.reload() }

    func buildMenu() {
        let main = NSMenu()
        let app = NSMenuItem(); main.addItem(app)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About hypnomix", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide hypnomix", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Quit hypnomix", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        app.submenu = appMenu
        let edit = NSMenuItem(); main.addItem(edit)
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        edit.submenu = editMenu
        let view = NSMenuItem(); main.addItem(view)
        let viewMenu = NSMenu(title: "View")
        let r = viewMenu.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r"); r.target = self
        view.submenu = viewMenu
        let win = NSMenuItem(); main.addItem(win)
        let winMenu = NSMenu(title: "Window")
        winMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        winMenu.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        win.submenu = winMenu
        NSApp.mainMenu = main
        NSApp.windowsMenu = winMenu
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
