package zw.co.tylonerp;

import android.net.Uri;
import android.webkit.JavascriptInterface;

import org.json.JSONException;
import org.json.JSONObject;

/**
 * What the pages inside the app can ask the phone to do.
 *
 * "TylonAndroid" is available to every page (the online web app and the offline screens): printing, and switching
 * between online and offline. "TylonStore" reads and writes the phone's data and signs in; it only answers the
 * app's own offline pages (file:///android_asset), never a web page, so nothing on the internet can reach it.
 *
 * Bridge methods run on a background thread; anything touching views is posted to the main thread.
 */
final class Bridge {
    private final MainActivity activity;

    Bridge(MainActivity activity) {
        this.activity = activity;
    }

    /** Available to every page. */
    final class Common {
        @JavascriptInterface
        public void print(String title) {
            activity.runOnUiThread(() -> Printer.printWebView(activity, activity.webView(), title));
        }

        /** Print a page from the TylonERP server (Quick sell receipts). Other sites are refused. */
        @JavascriptInterface
        public void printUrl(String url) {
            if (!activity.isServerUrl(url)) return;
            activity.runOnUiThread(() -> Printer.printUrl(activity, url, "TylonERP receipt"));
        }

        @JavascriptInterface
        public void openOffline() {
            activity.runOnUiThread(() -> activity.showOffline("chosen"));
        }

        @JavascriptInterface
        public String appVersion() {
            return BuildConfig.VERSION_NAME;
        }
    }

    /** The phone's data. Only the app's own offline pages may use it. */
    final class Data {
        private boolean allowed() {
            return activity.isLocalPage();
        }

        private String denied() {
            return "{\"ok\":false,\"error\":\"Not available here.\"}";
        }

        @JavascriptInterface
        public String state() {
            if (!allowed()) return denied();
            Prefs p = activity.prefs();
            JSONObject s = SyncManager.get(activity).state();
            try {
                s.put("ok", true);
                s.put("signed_in", p.signedIn());
                s.put("server", p.server());
                s.put("slug", p.slug());
                s.put("tenant", p.tenant());
                s.put("user", p.user());
                s.put("online", activity.hasNetwork());
                s.put("version", BuildConfig.VERSION_NAME);
            } catch (JSONException ignored) {
                // constant keys
            }
            return s.toString();
        }

        @JavascriptInterface
        public String products() { return allowed() ? Store.get(activity).products().toString() : "[]"; }

        @JavascriptInterface
        public String clients() { return allowed() ? Store.get(activity).clients().toString() : "[]"; }

        @JavascriptInterface
        public String debts() { return allowed() ? Store.get(activity).debts().toString() : "[]"; }

        @JavascriptInterface
        public String ops() { return allowed() ? Store.get(activity).ops(150).toString() : "[]"; }

        /** Save a change on the phone, then try to upload it straight away. */
        @JavascriptInterface
        public String queue(String kind, String dataJson, String summary) {
            if (!allowed()) return denied();
            JSONObject data;
            try {
                data = new JSONObject(dataJson == null ? "{}" : dataJson);
            } catch (JSONException e) {
                return "{\"ok\":false,\"error\":\"That change could not be read.\"}";
            }
            JSONObject res = Store.get(activity).queue(kind == null ? "" : kind, data, summary == null ? "" : summary);
            if (res.optBoolean("ok")) {
                SyncJobService.scheduleUpload(activity);
                if (activity.hasNetwork()) SyncManager.get(activity).requestSync();
            }
            return res.toString();
        }

        @JavascriptInterface
        public void sync() {
            if (allowed()) SyncManager.get(activity).requestSync();
        }

        @JavascriptInterface
        public void dismiss(String opId) {
            if (allowed()) Store.get(activity).dismiss(opId);
        }

        /** Sign in from the setup screen. The answer arrives in window.TylonSetup.onLogin(result). */
        @JavascriptInterface
        public void login(String server, String slug, String email, String password) {
            if (!allowed()) return;
            activity.signIn(server, slug, email, password);
        }

        @JavascriptInterface
        public String defaults() {
            if (!allowed()) return denied();
            Prefs p = activity.prefs();
            JSONObject o = new JSONObject();
            try {
                o.put("server", p.server());
                o.put("slug", p.slug());
                o.put("email", p.user().optString("email", ""));
            } catch (JSONException ignored) {
                // constant keys
            }
            return o.toString();
        }

        @JavascriptInterface
        public void openOnline() {
            if (allowed()) activity.runOnUiThread(activity::tryOnline);
        }

        /** Sign this phone out. Refused while changes are still waiting to upload, unless forced. */
        @JavascriptInterface
        public String signOut(boolean force) {
            if (!allowed()) return denied();
            int waiting = Store.get(activity).count("pending");
            if (waiting > 0 && !force) {
                return "{\"ok\":false,\"waiting\":" + waiting + "}";
            }
            activity.runOnUiThread(activity::signOut);
            return "{\"ok\":true}";
        }

        @JavascriptInterface
        public void printHtml(String html, String title) {
            if (!allowed()) return;
            activity.runOnUiThread(() -> Printer.printHtml(activity, html, title));
        }

        @JavascriptInterface
        public void openLink(String url) {
            if (!allowed() || url == null) return;
            Uri u = Uri.parse(url);
            if ("https".equals(u.getScheme()) || "http".equals(u.getScheme())) {
                activity.runOnUiThread(() -> activity.openExternal(u));
            }
        }
    }
}
