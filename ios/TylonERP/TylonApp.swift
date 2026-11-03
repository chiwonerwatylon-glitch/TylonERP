import SwiftUI

/// TylonERP for iPhone and iPad: the TylonERP web app in a full-screen web view, with the camera for barcodes,
/// printing through AirPrint, file downloads and a first-run screen to choose the business.
@main
struct TylonApp: App {
    var body: some Scene {
        WindowGroup { RootView() }
    }
}

struct RootView: View {
    @AppStorage("startURL") private var startURL: String = ""

    var body: some View {
        if let url = URL(string: startURL), !startURL.isEmpty {
            WebScreen(url: url, onChangeBusiness: { startURL = "" })
                .ignoresSafeArea(.container, edges: .bottom)
        } else {
            SetupView { startURL = $0.absoluteString }
        }
    }
}
