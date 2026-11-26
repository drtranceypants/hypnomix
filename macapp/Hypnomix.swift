// Hypnomix.app: a window around the local hypnomix app (`hypnomix app`). No network beyond this computer.
// Build: ./build.sh   (needs the Swift compiler from Xcode's command line tools)
import Cocoa
import WebKit

let port = Int(ProcessInfo.processInfo.environment["HYPNOMIX_PORT"] ?? "") ?? 8791   // a test copy can run beside the real one
let home = URL(string: "http://127.0.0.1:\(port)/")!

final class AppDelegate: NSObject, NSApplicationDelegate, WKUIDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var tries = 0
    var quitting = false       // a quit is under way (the question asked, the server being stopped)
    var forceQuit = false      // SIGTERM: the updater's helper (it refused while the session was unsaved), a logout, `kill`

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMenu()
        web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        web.uiDelegate = self
        web.navigationDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1040, height: 800),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "HypnoMix"
        window.contentView = web
        window.center()
        window.setFrameAutosaveName("HypnomixMain")
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        message("Starting HypnoMix…")
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
        p.arguments = ["-m", "hypnomix.cli", "app", "--no-open", "--port", "\(port)"] + (dawMode ? ["--daw"] : [])
        p.environment = serverEnv()
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do { try p.run() } catch {
            message("Could not start HypnoMix: \(error.localizedDescription)")
            return
        }
        server = p
        waitForServer()
    }

    // DAW mode, for a TEST build only: a kit placed in Contents/Resources/engine (macapp/build.sh --daw KIT) makes the app
    // open on the DAW view, and the server's supervisor (hypnomix/app/daw.py) finds Contents/Resources/engine/bin/hypnomix-engine
    // by itself. The installer no longer carries the engine: people add HypnoMix DAW from Setup (hypnomix/app/engine_addon.py),
    // and the DAW tab then appears like any other. This switch is found for one more version, and nothing depends on it.
    // HYPNOMIX_DAW=1 only opens the DAW view first (a developer's switch).
    var dawMode: Bool {
        let kit = Bundle.main.bundlePath + "/Contents/Resources/engine/bin/hypnomix-engine"
        return FileManager.default.isExecutableFile(atPath: kit) || ProcessInfo.processInfo.environment["HYPNOMIX_DAW"] == "1"
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
        // a developer build (macapp/build.sh --daw KIT) runs the checkout's Python, which can't see the kit from where
        // it is: name it. The installer's copy needs nothing (the server finds Contents/Resources/engine by itself).
        let kit = Bundle.main.bundlePath + "/Contents/Resources/engine/bin/hypnomix-engine"
        if bundled == nil, env["HYPNOMIX_ENGINE"] == nil, FileManager.default.isExecutableFile(atPath: kit) { env["HYPNOMIX_ENGINE"] = kit }
        return env
    }

    func waitForServer() {
        tries += 1
        isUp { up in
            if up { self.web.load(URLRequest(url: home)); return }
            if self.tries > 60 || self.server?.isRunning == false {
                self.message(self.bundled != nil
                    ? "HypnoMix did not start. Quit and open it again; if it still fails, download the installer again from hypnomix.bradfieldenterprises.org."
                    : "HypnoMix did not start. In Terminal, run: hypnomix app   and read what it says.")
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
        a.messageText = "Where is HypnoMix installed?"
        a.informativeText = "Choose the HypnoMix folder (the one you cloned or unzipped, after running the install steps in it)."
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

    // ---- quitting (⌘Q, closing the window, the Dock's Quit)
    // When the DAW is in use the session in the engine may have changes nobody saved, and stopping the server stops the engine.
    // So: ask the server (GET /api/daw/state "dirty"); if it is, offer Save / Don't Save / Cancel; then stop the server
    // and WAIT for it to exit (it stops the engine first, up to about 15 s) before the app itself quits.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitting { return .terminateLater }
        guard let p = server, p.isRunning else { return .terminateNow }        // a server this app did not start is left running
        quitting = true
        let stop = { self.stopServer { NSApp.reply(toApplicationShouldTerminate: true) } }
        if forceQuit { stop(); return .terminateLater }
        // HypnoMix DAW is an add-on, so the engine can be running in any window of this app: ask the server every time.
        // A test build that carries the engine (dawMode) also asks when the server does not answer; an ordinary window does not nag.
        serverIsDirty { dirty in
            if dirty == nil {                                                  // no answer is not "nothing unsaved"
                if !self.dawMode || self.askQuitUnchecked() { stop() } else { self.quitting = false; NSApp.reply(toApplicationShouldTerminate: false) }
                return
            }
            if dirty == false { stop(); return }
            switch self.askToSave() {
            case .save:
                self.saveSession { error in
                    if error == nil { stop(); return }
                    if self.askQuitAnyway(error ?? "") { stop() } else { self.quitting = false; NSApp.reply(toApplicationShouldTerminate: false) }
                }
            case .discard: stop()
            case .cancel: self.quitting = false; NSApp.reply(toApplicationShouldTerminate: false)
            }
        }
        return .terminateLater
    }

    func applicationWillTerminate(_ note: Notification) { server?.terminate() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    /// Ends the server this app started and calls `done` on the main queue once it has exited (after 25 s it is killed).
    func stopServer(_ done: @escaping () -> Void) {
        guard let p = server, p.isRunning else { done(); return }
        p.terminate()
        DispatchQueue.global().async {
            let end = Date().addingTimeInterval(25)
            while p.isRunning && Date() < end { Thread.sleep(forTimeInterval: 0.1) }
            if p.isRunning { kill(p.processIdentifier, SIGKILL) }
            DispatchQueue.main.async { done() }
        }
    }

    /// true / false as the server says; nil when it could not be asked (timeout, connection error, not a 200 with a "dirty" answer).
    func serverIsDirty(_ done: @escaping (Bool?) -> Void) {
        var req = URLRequest(url: home.appendingPathComponent("api/daw/state"))
        req.timeoutInterval = 3
        URLSession.shared.dataTask(with: req) { data, resp, _ in
            var dirty: Bool? = nil
            if (resp as? HTTPURLResponse)?.statusCode == 200, let d = data,
               let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any] { dirty = j["dirty"] as? Bool }
            DispatchQueue.main.async { done(dirty) }
        }.resume()
    }

    enum SaveAnswer { case save, discard, cancel }

    func askToSave() -> SaveAnswer {
        let a = NSAlert()
        a.messageText = "Save the session before quitting?"
        a.informativeText = "It has changes that are not saved. If you don't save, they are lost."
        a.addButton(withTitle: "Save")
        a.addButton(withTitle: "Cancel")
        a.addButton(withTitle: "Don't Save")
        switch a.runModal() {
        case .alertFirstButtonReturn: return .save
        case .alertThirdButtonReturn: return .discard
        default: return .cancel
        }
    }

    func askQuitUnchecked() -> Bool {
        let a = NSAlert()
        a.messageText = "Could not check for unsaved changes"
        a.informativeText = "The session did not answer. If it has changes that are not saved, quitting now loses them."
        a.addButton(withTitle: "Don't Quit")
        a.addButton(withTitle: "Quit Anyway")
        return a.runModal() == .alertSecondButtonReturn
    }

    func askQuitAnyway(_ why: String) -> Bool {
        let a = NSAlert()
        a.messageText = "The session could not be saved"
        a.informativeText = "\(why)\n\nQuit anyway and lose the unsaved changes?"
        a.addButton(withTitle: "Don't Quit")
        a.addButton(withTitle: "Quit Without Saving")
        return a.runModal() == .alertSecondButtonReturn
    }

    /// POST /api/daw/save with the page's own token (the page holds it: HX_TOKEN in the DAW view, TOKEN in the other pages).
    /// `done` gets nil when the server answered ok and the session is clean, otherwise the reason in words.
    func saveSession(_ done: @escaping (String?) -> Void) {
        web.evaluateJavaScript("typeof HX_TOKEN !== 'undefined' ? HX_TOKEN : (typeof TOKEN !== 'undefined' ? TOKEN : '')") { tok, _ in
            guard let token = tok as? String, !token.isEmpty else { done("The window does not hold the page's key right now."); return }
            var req = URLRequest(url: home.appendingPathComponent("api/daw/save"))
            req.httpMethod = "POST"
            req.timeoutInterval = 60
            req.setValue(token, forHTTPHeaderField: "X-Hypnomix")
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = Data("{}".utf8)
            URLSession.shared.dataTask(with: req) { data, resp, err in
                var why: String? = "No answer from the engine."
                if let err = err { why = err.localizedDescription }
                else if let d = data, let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any] {
                    if (resp as? HTTPURLResponse)?.statusCode == 200, (j["dirty"] as? Bool) == false { why = nil }
                    else { why = (j["error"] as? String) ?? "The engine did not confirm the save." }
                }
                DispatchQueue.main.async { done(why) }
            }.resume()
        }
    }

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

    // ---- File → New Session… / Open Session… (DAW mode): a file panel here, then the DAW view asks the app's
    // supervisor (POST /api/daw/new or /api/daw/open, with the page's own token) through HX.menuSession
    var pendingSession: [String: String]?

    @objc func newSession() {
        let panel = NSSavePanel()
        panel.title = "New Session"
        panel.message = "Name the new session. HypnoMix makes a folder of that name here, with the session inside it."
        panel.prompt = "Create"
        panel.nameFieldStringValue = "New Song"
        panel.canCreateDirectories = true
        panel.directoryURL = FileManager.default.urls(for: .musicDirectory, in: .userDomainMask).first
        guard panel.runModal() == .OK, let url = panel.url else { return }
        sendSession(["op": "new", "folder": url.deletingLastPathComponent().path, "name": url.lastPathComponent])
    }

    @objc func openSession() {
        let panel = NSOpenPanel()
        panel.title = "Open Session"
        panel.message = "Choose a session: its .ardour file, or its folder."
        panel.prompt = "Open"
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        sendSession(["op": "open", "path": url.path])
    }

    // File → Import Project…: a project from another DAW becomes a NEW session beside it (the DAW view runs the
    // import through POST /api/daw/import and offers to open the result). A .logicx project is a package: allowed whole.
    @objc func importProject() {
        let panel = NSOpenPanel()
        panel.title = "Import Project"
        panel.message = "Choose a project from another DAW: a .als set, a .logicx project, a .dawproject file or a .rpp project (a .ptx session or an .aaf export with the HypnoMix DAW add-on). It is only read."
        panel.prompt = "Import"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.treatsFilePackagesAsDirectories = false
        panel.allowsMultipleSelection = false
        let outside = NSButton(checkboxWithTitle: "Also copy audio from outside the project", target: nil, action: nil)
        outside.state = .off
        panel.accessoryView = outside
        panel.isAccessoryViewDisclosed = true
        guard panel.runModal() == .OK, let url = panel.url else { return }
        sendSession(["op": "import", "path": url.path, "allow_outside": outside.state == .on ? "1" : "0"])
    }

    func sendSession(_ req: [String: String]) {
        if web.url?.host == "127.0.0.1", web.url?.path.hasPrefix("/daw") == true { callMenu(req); return }
        pendingSession = req                                   // another page (or still starting): the DAW view first
        web.load(URLRequest(url: home.appendingPathComponent("daw/")))
    }

    func callMenu(_ req: [String: String]) {
        guard let data = try? JSONSerialization.data(withJSONObject: req), let json = String(data: data, encoding: .utf8) else { return }
        web.evaluateJavaScript("window.HX && HX.menuSession ? (HX.menuSession(\(json)), true) : false") { ok, _ in
            if (ok as? Bool) != true { self.alert("The DAW view is not ready yet: try again in a moment.") }
        }
    }

    func webView(_ w: WKWebView, didFinish nav: WKNavigation!) {
        guard let req = pendingSession, w.url?.path.hasPrefix("/daw") == true else { return }
        pendingSession = nil
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.callMenu(req) }   // its scripts set HX up first
    }

    func alert(_ text: String) { let a = NSAlert(); a.messageText = text; a.runModal() }

    func buildMenu() {
        let main = NSMenu()
        let app = NSMenuItem(); main.addItem(app)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About HypnoMix", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide HypnoMix", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(withTitle: "Quit HypnoMix", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        app.submenu = appMenu
        if dawMode {
            let file = NSMenuItem(); main.addItem(file)
            let fileMenu = NSMenu(title: "File")
            let n = fileMenu.addItem(withTitle: "New Session…", action: #selector(newSession), keyEquivalent: "n"); n.target = self
            let o = fileMenu.addItem(withTitle: "Open Session…", action: #selector(openSession), keyEquivalent: "o"); o.target = self
            fileMenu.addItem(.separator())
            let i = fileMenu.addItem(withTitle: "Import Project…", action: #selector(importProject), keyEquivalent: "i"); i.target = self
            file.submenu = fileMenu
        }
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
// SIGTERM (the updater's helper, a logout, `kill`) quits like ⌘Q: the server is told to stop, and it stops the engine
signal(SIGTERM, SIG_IGN)
let quitOnTerm = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
quitOnTerm.setEventHandler { delegate.forceQuit = true; NSApp.terminate(nil) }   // no question here: the updater refuses while unsaved
quitOnTerm.resume()
app.setActivationPolicy(.regular)
app.run()
