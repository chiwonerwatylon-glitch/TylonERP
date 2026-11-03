import SwiftUI

/// First run: which TylonERP server and which business. Accepts a pasted sign-in link too.
struct SetupView: View {
    var onDone: (URL) -> Void
    @State private var server: String = (Bundle.main.object(forInfoDictionaryKey: "TylonServerURL") as? String) ?? "https://"
    @State private var business: String = ""
    @State private var error: String?
    private let green = Color(red: 15 / 255, green: 92 / 255, blue: 74 / 255)

    var body: some View {
        NavigationView {
            Form {
                Section {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("TylonERP").font(.largeTitle.bold()).foregroundColor(green)
                        Text("Sell, count stock and keep track of who owes what.").foregroundColor(.secondary)
                    }.padding(.vertical, 8)
                }
                Section(header: Text("Your business"), footer: Text("The part after /t/ in your sign-in link, for example mbare. You can also paste the whole link.")) {
                    TextField("Business name or sign-in link", text: $business)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                }
                Section(header: Text("Server")) {
                    TextField("https://", text: $server)
                        .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                }
                if let error { Section { Text(error).foregroundColor(.red) } }
                Section {
                    Button(action: open) { Text("Continue").frame(maxWidth: .infinity).font(.headline) }
                        .tint(green)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
        }
        .navigationViewStyle(.stack)
    }

    private func open() {
        let raw = business.trimmingCharacters(in: .whitespacesAndNewlines)
        if raw.contains("/t/"), let url = URL(string: raw.hasPrefix("http") ? raw : "https://" + raw), url.host != nil {
            return onDone(url)
        }
        let slug = raw.lowercased().replacingOccurrences(of: " ", with: "-")
        guard !slug.isEmpty, slug.range(of: "^[a-z0-9][a-z0-9-]*$", options: .regularExpression) != nil else {
            error = "Enter your business name as it appears in your sign-in link."
            return
        }
        var base = server.trimmingCharacters(in: .whitespacesAndNewlines)
        if !base.hasPrefix("http") { base = "https://" + base }
        while base.hasSuffix("/") { base.removeLast() }
        guard let url = URL(string: base + "/t/" + slug), url.host != nil else {
            error = "Check the server address."
            return
        }
        onDone(url)
    }
}
