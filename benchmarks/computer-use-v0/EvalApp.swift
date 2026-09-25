import AppKit
import Foundation

private struct EvalState: Codable {
    let caseID: String
    let nonce: String
    var recordCount = 0
    var resetCount = 0
    var cancelCount = 0
    var submitCount = 0
    var discardCount = 0
    var submittedText = ""
}

private final class EvalApp: NSObject {
    private let statePath: URL
    private var state: EvalState
    private var window: NSWindow?
    private var input: NSTextField?
    private var status: NSTextField?

    init(caseID: String, nonce: String, statePath: URL) {
        self.state = EvalState(caseID: caseID, nonce: nonce)
        self.statePath = statePath
        super.init()
    }

    private func save() {
        do {
            let data = try JSONEncoder().encode(state)
            try data.write(to: statePath, options: .atomic)
        } catch {
            fputs("Could not write fixture state: \(error)\n", stderr)
            exit(1)
        }
    }

    private func label(_ text: String, y: CGFloat, width: CGFloat = 440) -> NSTextField {
        let field = NSTextField(labelWithString: text)
        field.frame = NSRect(x: 24, y: y, width: width, height: 26)
        field.font = NSFont.systemFont(ofSize: 17)
        field.lineBreakMode = .byTruncatingTail
        return field
    }

    private func button(_ title: String, x: CGFloat, y: CGFloat, action: Selector) -> NSButton {
        let control = NSButton(title: title, target: self, action: action)
        control.frame = NSRect(x: x, y: y, width: 128, height: 38)
        control.bezelStyle = .rounded
        return control
    }

    func start() {
        save()
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        let window = NSWindow(
            contentRect: NSRect(x: 260, y: 250, width: 500, height: 280),
            styleMask: [.titled], backing: .buffered, defer: false
        )
        window.title = "Computer Use Eval: \(state.caseID)"
        let content = window.contentView!
        content.addSubview(label("Computer use evaluation", y: 218))
        switch state.caseID {
        case "read-code":
            let code = label("Reference code: \(state.nonce)", y: 152)
            code.font = NSFont.monospacedSystemFont(ofSize: 24, weight: .bold)
            content.addSubview(code)
            content.addSubview(label("Report the six digits shown above.", y: 102))
        case "button":
            content.addSubview(label("Click Record exactly once.", y: 165))
            content.addSubview(button("Record", x: 25, y: 105, action: #selector(record)))
            content.addSubview(button("Reset", x: 176, y: 105, action: #selector(reset)))
            content.addSubview(button("Cancel", x: 327, y: 105, action: #selector(cancel)))
            let status = label("No button pressed", y: 56)
            content.addSubview(status)
            self.status = status
        case "form":
            content.addSubview(label("Enter phrase: \(state.nonce)", y: 165))
            let input = NSTextField(frame: NSRect(x: 25, y: 112, width: 445, height: 28))
            input.placeholderString = "Type phrase here"
            content.addSubview(input)
            self.input = input
            content.addSubview(button("Submit", x: 25, y: 57, action: #selector(submit)))
            content.addSubview(button("Discard", x: 176, y: 57, action: #selector(discard)))
            let status = label("Nothing submitted", y: 18)
            status.font = NSFont.systemFont(ofSize: 13)
            content.addSubview(status)
            self.status = status
        default:
            fputs("Unknown case: \(state.caseID)\n", stderr)
            exit(2)
        }
        self.window = window
        window.makeKeyAndOrderFront(nil)
        app.activate(ignoringOtherApps: true)
        app.run()
    }

    @objc private func record() {
        state.recordCount += 1
        status?.stringValue = "Recorded"
        save()
    }

    @objc private func reset() {
        state.resetCount += 1
        status?.stringValue = "Reset pressed"
        save()
    }

    @objc private func cancel() {
        state.cancelCount += 1
        status?.stringValue = "Cancel pressed"
        save()
    }

    @objc private func submit() {
        state.submitCount += 1
        state.submittedText = input?.stringValue ?? ""
        status?.stringValue = "Submitted"
        save()
    }

    @objc private func discard() {
        state.discardCount += 1
        input?.stringValue = ""
        status?.stringValue = "Discarded"
        save()
    }
}

guard CommandLine.arguments.count == 4 else {
    fputs("Usage: EvalApp CASE_ID NONCE STATE_PATH\n", stderr)
    exit(2)
}
EvalApp(
    caseID: CommandLine.arguments[1],
    nonce: CommandLine.arguments[2],
    statePath: URL(fileURLWithPath: CommandLine.arguments[3])
).start()
