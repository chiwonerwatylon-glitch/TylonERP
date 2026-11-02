package zw.co.tylonerp;

import android.Manifest;
import android.app.Activity;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Insets;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.CookieManager;
import android.webkit.PermissionRequest;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.ProgressBar;
import android.widget.Toast;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.UnsupportedEncodingException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;

/**
 * The app's single screen: a web view that shows either
 * - the TylonERP web app from the server (online: every feature, exactly as on the web), or
 * - the offline screens bundled in the app (assets/offline), which sell, count stock and record payments on the
 *   phone and upload them later.
 * It switches to offline by itself when the server cannot be reached, and offers to go back online when the
 * connection returns.
 */
public class MainActivity extends Activity implements SyncManager.Listener {
    private static final String LOCAL = "file:///android_asset/offline/";
    private static final int REQ_FILE = 41;
    private static final int REQ_CAMERA = 42;

    private WebView web;
    private ProgressBar progress;
    private Prefs prefs;
    private ConnectivityManager connectivity;
    private ConnectivityManager.NetworkCallback networkCallback;

    private volatile boolean localPage;          // read by the bridge on its own thread
    private boolean webSessionStarted;           // the web view has been signed in with the phone's token
    private ValueCallback<Uri[]> fileCallback;
    private PermissionRequest pendingPermission;

    // ------------------------------------------------------------------ lifecycle

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = new Prefs(this);
        connectivity = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(getColor(R.color.canvas));
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setIndeterminate(false);
        progress.setMax(100);
        progress.setVisibility(View.GONE);
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3), Gravity.TOP);
        root.addView(progress, lp);
        setContentView(root);
        setUpEdgeToEdge(root);
        setUpWebView();

        SyncManager.get(this).addListener(this);
        SyncJobService.schedulePeriodic(this);
        watchNetwork();
        start();
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
        if (prefs.signedIn() && hasNetwork()) SyncManager.get(this).requestSync();
    }

    @Override
    protected void onPause() {
        web.onPause();
        CookieManager.getInstance().flush();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        SyncManager.get(this).removeListener(this);
        if (networkCallback != null) {
            try {
                connectivity.unregisterNetworkCallback(networkCallback);
            } catch (RuntimeException ignored) {
                // already unregistered
            }
        }
        web.destroy();
        super.onDestroy();
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        // Dark mode switched while the app is open: recolour the bars to match.
        View root = (View) web.getParent();
        root.setBackgroundColor(getColor(R.color.canvas));
        applyBarColours();
    }

    /** First screen: sign-in if this phone has no account yet, otherwise the online app (or offline if it cannot). */
    private void start() {
        if (!prefs.signedIn()) {
            loadLocal("setup.html");
        } else {
            tryOnline();
        }
    }

    // ------------------------------------------------------------------ online / offline

    /** Check the server, then open the web app; if it cannot be reached, open the offline screens. */
    void tryOnline() {
        if (!prefs.signedIn()) {
            loadLocal("setup.html");
            return;
        }
        if (!hasNetwork()) {
            showOffline("no-network");
            return;
        }
        progress.setVisibility(View.VISIBLE);
        progress.setProgress(10);
        final String server = prefs.server();
        new Thread(() -> {
            final boolean up = Api.reachable(server);
            runOnUiThread(() -> {
                if (isFinishing()) return;
                if (up) openWebApp();
                else showOffline("server");
            });
        }, "tylonerp-check").start();
        SyncManager.get(this).requestSync();
    }

    private void openWebApp() {
        String server = prefs.server();
        String slug = prefs.slug();
        if (!webSessionStarted && prefs.token() != null) {
            // Sign the web view in with the phone's token, so nobody has to type their password twice.
            webSessionStarted = true;
            web.postUrl(server + "/t/" + slug + "/mobile-session", ("token=" + enc(prefs.token())).getBytes(StandardCharsets.UTF_8));
        } else {
            web.loadUrl(server + "/t/" + slug + "/app/");
        }
    }

    void showOffline(String reason) {
        if (!prefs.signedIn()) {
            loadLocal("setup.html");
            return;
        }
        loadLocal("index.html#" + reason);
    }

    private void loadLocal(String page) {
        localPage = true;
        web.loadUrl(LOCAL + page);
    }

    /** Sign in from the setup screen (runs on a background thread, answers the page when done). */
    void signIn(String serverRaw, String slugRaw, String email, String password) {
        new Thread(() -> {
            JSONObject result = new JSONObject();
            try {
                String server = Prefs.normaliseServer(serverRaw);
                String slug = slugFrom(slugRaw);
                if (server.isEmpty() || slug.isEmpty()) throw new Api.ApiException(400, "Enter the server address and your business sign-in name.", false);
                JSONObject body = new JSONObject();
                body.put("slug", slug);
                body.put("email", email == null ? "" : email.trim());
                body.put("password", password == null ? "" : password);
                JSONObject r = Api.post(server, "/api/v1/login", null, body);
                String previousSlug = prefs.slug();
                boolean otherBusiness = !slug.equals(previousSlug) || !server.equals(prefs.server());
                if (otherBusiness && Store.get(this).count("pending") > 0) {
                    throw new Api.ApiException(409, "This phone still has changes for " + previousSlug
                            + " waiting to upload. Sign in to that business again so they can upload first.", false);
                }
                if (otherBusiness) Store.get(this).clearAll();
                prefs.saveLogin(server, slug, r.getString("token"), r.optJSONObject("tenant"), r.optJSONObject("user"));
                webSessionStarted = false;
                SyncManager.get(this).runSync();  // download products and clients before the first offline sale
                result.put("ok", true);
                result.put("must_change_password", r.optBoolean("must_change_password", false));
            } catch (Api.ApiException e) {
                putQuiet(result, "ok", false);
                putQuiet(result, "error", e.getMessage());
            } catch (java.io.IOException e) {
                putQuiet(result, "ok", false);
                putQuiet(result, "error", "Could not reach the server. Check the address and your connection.");
            } catch (JSONException | RuntimeException e) {
                putQuiet(result, "ok", false);
                putQuiet(result, "error", "Sign-in failed: " + e.getMessage());
            }
            final String js = "window.TylonSetup && TylonSetup.onLogin(" + result + ")";
            runOnUiThread(() -> {
                web.evaluateJavascript(js, null);
                if (result.optBoolean("ok")) tryOnline();
            });
        }, "tylonerp-login").start();
    }

    void signOut() {
        SyncJobService.cancelAll(this);
        Store.get(this).clearAll();
        prefs.signOut();
        CookieManager.getInstance().removeAllCookies(null);
        webSessionStarted = false;
        loadLocal("setup.html");
    }

    /** Accepts "mbare", "/t/mbare" or a full sign-in link such as https://example.com/t/mbare. */
    static String slugFrom(String raw) {
        String s = raw == null ? "" : raw.trim().toLowerCase();
        int i = s.indexOf("/t/");
        if (i >= 0) s = s.substring(i + 3);
        int slash = s.indexOf('/');
        if (slash >= 0) s = s.substring(0, slash);
        return s.matches("[a-z0-9][a-z0-9-]*") ? s : "";
    }

    // ------------------------------------------------------------------ sync and network → offline screens

    @Override
    public void onSyncState(JSONObject state) {
        final String js = "window.TylonOffline && TylonOffline.onSync(" + state + ")";
        runOnUiThread(() -> {
            if (localPage) web.evaluateJavascript(js, null);
        });
    }

    private void watchNetwork() {
        networkCallback = new ConnectivityManager.NetworkCallback() {
            @Override
            public void onAvailable(Network network) {
                SyncManager.get(MainActivity.this).requestSync();
                tellOffline(true);
            }

            @Override
            public void onLost(Network network) {
                tellOffline(hasNetwork());
            }
        };
        try {
            connectivity.registerDefaultNetworkCallback(networkCallback);
        } catch (RuntimeException e) {
            networkCallback = null;  // too many callbacks registered on this device; sync still runs on resume
        }
    }

    private void tellOffline(boolean online) {
        runOnUiThread(() -> {
            if (localPage) web.evaluateJavascript("window.TylonOffline && TylonOffline.onNetwork(" + online + ")", null);
        });
    }

    boolean hasNetwork() {
        if (connectivity == null) return false;
        Network n = connectivity.getActiveNetwork();
        NetworkCapabilities caps = n == null ? null : connectivity.getNetworkCapabilities(n);
        return caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
    }

    // ------------------------------------------------------------------ the web view

    private void setUpWebView() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);  // the camera preview for scanning plays by itself
        s.setAllowFileAccess(false);                   // bundled pages load from android_asset, which is unaffected
        s.setAllowContentAccess(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setSupportZoom(false);
        s.setUserAgentString(s.getUserAgentString() + " " + Api.USER_AGENT);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);

        Bridge bridge = new Bridge(this);
        web.addJavascriptInterface(bridge.new Common(), "TylonAndroid");
        web.addJavascriptInterface(bridge.new Data(), "TylonStore");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                String url = u.toString();
                if (url.startsWith(LOCAL) || isServerUrl(url)) return false;
                openExternal(u);  // phone numbers, email, the EcoCash portal and other sites open outside the app
                return true;
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                localPage = url != null && url.startsWith(LOCAL);
                progress.setVisibility(View.VISIBLE);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                localPage = url != null && url.startsWith(LOCAL);
                progress.setVisibility(View.GONE);
                CookieManager.getInstance().flush();
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                // The server cannot be reached while opening a page: carry on offline instead of showing an error.
                if (request.isForMainFrame() && !request.getUrl().toString().startsWith(LOCAL)) showOffline("connection");
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                int code = response.getStatusCode();
                if (request.isForMainFrame() && (code == 502 || code == 503 || code == 504)) showOffline("server");
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int p) {
                progress.setProgress(p);
                if (p >= 100) progress.setVisibility(View.GONE);
            }

            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                try {
                    startActivityForResult(params.createIntent(), REQ_FILE);
                } catch (ActivityNotFoundException e) {
                    fileCallback = null;
                    callback.onReceiveValue(null);
                    toast("No app on this phone can pick a file.");
                }
                return true;
            }

            @Override
            public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> handleCameraRequest(request));
            }

            @Override
            public void onPermissionRequestCanceled(PermissionRequest request) {
                if (pendingPermission == request) pendingPermission = null;
            }
        });

        // Downloads (for example the stock import template) go through Android's download manager.
        web.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
            try {
                DownloadManager.Request r = new DownloadManager.Request(Uri.parse(url));
                r.addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url));
                r.addRequestHeader("User-Agent", userAgent);
                r.setMimeType(mimeType);
                String name = URLUtil.guessFileName(url, contentDisposition, mimeType);
                r.setTitle(name);
                r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
                }
                DownloadManager dm = (DownloadManager) getSystemService(Context.DOWNLOAD_SERVICE);
                if (dm != null) {
                    dm.enqueue(r);
                    toast("Downloading " + name);
                }
            } catch (RuntimeException e) {
                toast("Could not download that file.");
            }
        });
    }

    private void handleCameraRequest(PermissionRequest request) {
        String origin = String.valueOf(request.getOrigin());
        boolean ours = origin.startsWith("file:") || isServerUrl(origin);
        boolean wantsCamera = false;
        for (String r : request.getResources()) {
            if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(r)) wantsCamera = true;
        }
        if (!ours || !wantsCamera) {
            request.deny();
            return;
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            request.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
        } else {
            pendingPermission = request;
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode != REQ_CAMERA || pendingPermission == null) return;
        PermissionRequest r = pendingPermission;
        pendingPermission = null;
        if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
            r.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
        } else {
            r.deny();
            toast("Allow camera access in the phone's settings to scan barcodes.");
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_FILE && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            fileCallback = null;
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (localPage) {
            // Let the offline screens close a form or go back to the first tab before leaving the app.
            web.evaluateJavascript("(window.TylonOffline && TylonOffline.back()) ? 'handled' : 'leave'", value -> {
                if (!"\"handled\"".equals(value)) moveTaskToBack(true);
            });
        } else if (web.canGoBack()) {
            web.goBack();
        } else {
            moveTaskToBack(true);
        }
    }

    // ------------------------------------------------------------------ window insets and bar colours

    /** Draw behind the status and navigation bars on every Android version, padding the content to clear them. */
    @SuppressWarnings("deprecation")
    private void setUpEdgeToEdge(View root) {
        Window w = getWindow();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Api30.edgeToEdge(w);
        } else {
            w.getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                    | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }
        w.setStatusBarColor(Color.TRANSPARENT);
        w.setNavigationBarColor(Color.TRANSPARENT);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                Api30.pad(v, insets);
            } else {
                v.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                        insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            }
            return insets;
        });
        applyBarColours();
    }

    /** Dark icons on the light canvas, light icons in dark mode. */
    @SuppressWarnings("deprecation")
    private void applyBarColours() {
        boolean night = (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
        Window w = getWindow();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Api30.barIcons(w, night);
        } else {
            View d = w.getDecorView();
            int flags = d.getSystemUiVisibility();
            int light = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) light |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            d.setSystemUiVisibility(night ? (flags & ~light) : (flags | light));
        }
    }

    /** Calls that only exist on Android 11 and later, kept apart so older phones never load them. */
    @android.annotation.TargetApi(Build.VERSION_CODES.R)
    private static final class Api30 {
        @SuppressWarnings("deprecation")  // still the way to opt in on Android 11 to 14; Android 15 does it by default
        static void edgeToEdge(Window w) {
            w.setDecorFitsSystemWindows(false);
        }

        static void pad(View v, WindowInsets insets) {
            Insets i = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime() | WindowInsets.Type.displayCutout());
            v.setPadding(i.left, i.top, i.right, i.bottom);
        }

        static void barIcons(Window w, boolean night) {
            WindowInsetsController c = w.getInsetsController();
            if (c == null) return;
            int mask = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
            c.setSystemBarsAppearance(night ? 0 : mask, mask);
        }
    }

    // ------------------------------------------------------------------ helpers used by the bridge

    WebView webView() { return web; }

    Prefs prefs() { return prefs; }

    boolean isLocalPage() { return localPage; }

    /** True for addresses on the TylonERP server this phone is set up for. */
    boolean isServerUrl(String url) {
        String server = prefs.server();
        if (url == null || server.isEmpty()) return false;
        return url.equals(server) || url.startsWith(server + "/");
    }

    void openExternal(Uri uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException e) {
            toast("No app on this phone can open that link.");
        }
    }

    private void toast(String msg) {
        runOnUiThread(() -> Toast.makeText(this, msg, Toast.LENGTH_LONG).show());
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private static String enc(String s) {
        try {
            return URLEncoder.encode(s, "UTF-8");
        } catch (UnsupportedEncodingException e) {
            return s;
        }
    }

    private static void putQuiet(JSONObject o, String k, Object v) {
        try {
            o.put(k, v);
        } catch (JSONException ignored) {
            // constant keys
        }
    }
}
