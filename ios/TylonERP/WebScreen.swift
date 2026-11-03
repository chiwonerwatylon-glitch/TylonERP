import SwiftUI
import UIKit
import WebKit

struct WebScreen: UIViewControllerRepresentable {
    let url: URL
    let onChangeBusiness: () -> Void

    func makeUIViewController(context: Context) -> WebViewController {
        WebViewController(start: url, onChangeBusiness: onChangeBusiness)
    }

    func updateUIViewController(_ controller: WebViewController, context: Context) {}
}

/// The web view and everything the web app asks of the phone.
final class WebViewController: UIViewController, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
    private let start: URL
    private let onChangeBusiness: () -> Void
    private var web: WKWebView!
    private var printer: WKWebView?
    private let progress = UIProgressView(progressViewStyle: .bar)
    private var observation: NSKeyValueObservation?
    private var downloadURL: URL?

    init(start: URL, onChangeBusiness: @escaping () -> Void) {
        self.start = start
        self.onChangeBusiness = onChangeBusiness
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = UIColor(red: 238 / 255, green: 241 / 255, blue: 239 / 255, alpha: 1)

        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        config.applicationNameForUserAgent = "TylonERP-iOS/2.0"
        let content = WKUserContentController()
        // window.print() in any frame asks the app to print that page through AirPrint.
        let printShim = "window.print = function () { window.webkit.messageHandlers.printUrl.postMessage(location.href); };"
        content.addUserScript(WKUserScript(source: printShim, injectionTime: .atDocumentStart, forMainFrameOnly: false))
        content.add(self, name: "printUrl")
        content.add(self, name: "changeBusiness")
        config.userContentController = content

        web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true
        web.scrollView.contentInsetAdjustmentBehavior = .automatic
        web.isOpaque = false
        web.backgroundColor = view.backgroundColor
        let refresh = UIRefreshControl()
        refresh.addTarget(self, action: #selector(reload(_:)), for: .valueChanged)
        web.scrollView.refreshControl = refresh

        web.translatesAutoresizingMaskIntoConstraints = false
        progress.translatesAutoresizingMaskIntoConstraints = false
        progress.progressTintColor = UIColor(red: 15 / 255, green: 92 / 255, blue: 74 / 255, alpha: 1)
        view.addSubview(web)
        view.addSubview(progress)
        NSLayoutConstraint.activate([
            web.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            web.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            web.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            web.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            progress.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            progress.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            progress.trailingAnchor.constraint(equalTo: view.trailingAnchor),
        ])
        observation = web.observe(\.estimatedProgress) { [weak self] web, _ in
            self?.progress.progress = Float(web.estimatedProgress)
            self?.progress.isHidden = web.estimatedProgress >= 1
        }
        web.load(URLRequest(url: start))
    }

    @objc private func reload(_ sender: UIRefreshControl) {
        if web.url == nil || web.url?.scheme == "about" { web.load(URLRequest(url: start)) } else { web.reload() }
        sender.endRefreshing()
    }

    // MARK: navigation

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { return decisionHandler(.allow) }
        if ["tel", "mailto", "sms", "whatsapp"].contains(url.scheme ?? "") {
            UIApplication.shared.open(url)
            return decisionHandler(.cancel)
        }
        // Links to other sites open in Safari; the app stays on the TylonERP server.
        if action.navigationType == .linkActivated, let host = url.host, host != start.host {
            UIApplication.shared.open(url)
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let disposition = (response.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition") ?? ""
        if !response.canShowMIMEType || disposition.lowercased().hasPrefix("attachment") {
            decisionHandler(.download)
        } else {
            decisionHandler(.allow)
        }
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let dest = FileManager.default.temporaryDirectory.appendingPathComponent(suggestedFilename)
        try? FileManager.default.removeItem(at: dest)
        downloadURL = dest
        completionHandler(dest)
    }

    func downloadDidFinish(_ download: WKDownload) {
        guard let file = downloadURL else { return }
        let share = UIActivityViewController(activityItems: [file], applicationActivities: nil)
        share.popoverPresentationController?.sourceView = view
        present(share, animated: true)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled { return }
        if ns.domain == "WebKitErrorDomain" && ns.code == 102 { return }  // handed over as a download
        showOffline(message: error.localizedDescription)
    }

    private func showOffline(message: String) {
        let safe = message.replacingOccurrences(of: "<", with: "&lt;")
        let html = """
        <!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
        <body style="font:17px -apple-system,system-ui;background:#eef1ef;color:#17201d;display:grid;place-items:center;min-height:90vh;text-align:center;padding:24px">
        <div><h2 style="margin:0 0 8px">No connection</h2><p style="color:#5b6964">\(safe)</p>
        <p style="color:#5b6964">Your cart on the Register is kept on this phone.</p>
        <button onclick="location.href='\(start.absoluteString)'" style="font:600 17px -apple-system;background:#0f5c4a;color:#fff;border:0;border-radius:12px;padding:14px 22px">Try again</button>
        <p><button onclick="webkit.messageHandlers.changeBusiness.postMessage(1)" style="font:15px -apple-system;background:none;border:0;color:#0f5c4a;margin-top:12px">Change business or server</button></p></div>
        """
        web.loadHTMLString(html, baseURL: nil)
    }

    // MARK: pages asking for the camera, dialogs and new windows

    @available(iOS 15.0, *)
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        decisionHandler(origin.host == start.host && type == .camera ? .grant : .prompt)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { webView.load(URLRequest(url: url)) }
        return nil
    }

    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        let a = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
        present(a, animated: true)
    }

    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        a.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(true) })
        present(a, animated: true)
    }

    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        let a = UIAlertController(title: nil, message: prompt, preferredStyle: .alert)
        a.addTextField { $0.text = defaultText; $0.keyboardType = .decimalPad }
        a.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(nil) })
        a.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(a.textFields?.first?.text) })
        present(a, animated: true)
    }

    // MARK: printing receipts (AirPrint) and switching business

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        if message.name == "changeBusiness" {
            onChangeBusiness()
            return
        }
        guard message.name == "printUrl", let s = message.body as? String, let url = URL(string: s) else { return }
        if url == web.url {
            present(printing: web.viewPrintFormatter(), name: web.title)
            return
        }
        // Load the receipt in a hidden web view (same cookies), then print it.
        let p = WKWebView(frame: CGRect(x: 0, y: 0, width: 400, height: 800), configuration: web.configuration)
        p.navigationDelegate = PrintLoader.shared
        PrintLoader.shared.onLoad = { [weak self] loaded in
            self?.present(printing: loaded.viewPrintFormatter(), name: loaded.title)
        }
        printer = p
        p.load(URLRequest(url: url))
    }

    private func present(printing formatter: UIPrintFormatter, name: String?) {
        let info = UIPrintInfo(dictionary: nil)
        info.outputType = .general
        info.jobName = name ?? "Receipt"
        let pc = UIPrintInteractionController.shared
        pc.printInfo = info
        pc.printFormatter = formatter
        pc.present(animated: true)
    }
}

/// Waits for a hidden receipt page to finish loading before it is printed.
final class PrintLoader: NSObject, WKNavigationDelegate {
    static let shared = PrintLoader()
    var onLoad: ((WKWebView) -> Void)?

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // Give the receipt's fonts a moment to settle.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in
            self?.onLoad?(webView)
            self?.onLoad = nil
        }
    }
}
