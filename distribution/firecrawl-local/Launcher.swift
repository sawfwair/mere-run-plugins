import AppKit

@MainActor
final class FirecrawlLauncher: NSObject, NSApplicationDelegate {
    private let service = Process()
    private let status = NSTextField(wrappingLabelWithString: "Starting Firecrawl Local…")
    private var window: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 145),
            styleMask: [.titled, .closable, .miniaturizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Firecrawl Local"
        window.isReleasedWhenClosed = false
        let quit = NSButton(title: "Quit", target: NSApp, action: #selector(NSApplication.terminate(_:)))
        let stack = NSStackView(views: [status, quit])
        status.preferredMaxLayoutWidth = 376
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 18
        stack.edgeInsets = NSEdgeInsets(top: 22, left: 22, bottom: 22, right: 22)
        window.contentView = stack
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        self.window = window

        guard let binary = Bundle.main.url(forAuxiliaryExecutable: "firecrawl-local") else {
            status.stringValue = "The Firecrawl executable is missing. Reinstall the standalone app."
            return
        }

        service.executableURL = binary
        service.arguments = ["--browser", "never", "serve", "--host", "127.0.0.1", "--port", "3002"]
        var environment = ProcessInfo.processInfo.environment.filter { !$0.key.hasPrefix("FIRECRAWL_") }
        environment["FIRECRAWL_CLOUD"] = "off"
        service.environment = environment
        service.terminationHandler = { [weak self] process in
            let code = process.terminationStatus
            DispatchQueue.main.async {
                self?.status.stringValue = "Firecrawl stopped (exit \(code)). Check whether port 3002 is in use."
            }
        }
        do {
            try service.run()
            status.stringValue = "Firecrawl Local listens on 127.0.0.1:3002. Keep this app open while using the Mere plugin."
        } catch {
            status.stringValue = "Firecrawl could not start. \(error.localizedDescription)"
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        if service.isRunning {
            service.terminate()
        }
    }
}

@main
struct FirecrawlLocalApp {
    @MainActor
    static func main() {
        let launcher = FirecrawlLauncher()
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        app.delegate = launcher
        app.run()
    }
}
