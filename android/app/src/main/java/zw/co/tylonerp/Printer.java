package zw.co.tylonerp;

import android.app.Activity;
import android.content.Context;
import android.print.PrintAttributes;
import android.print.PrintDocumentAdapter;
import android.print.PrintManager;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/**
 * Printing through Android's print service (Wi-Fi, Bluetooth and USB printers, or "Save as PDF").
 * A web view cannot print with window.print(), so the pages call the bridge, which lands here.
 */
final class Printer {
    /** Holds the off-screen page until it has been handed to the print service. */
    private static WebView pending;

    private Printer() {}

    static void printWebView(Activity activity, WebView view, String title) {
        PrintManager pm = (PrintManager) activity.getSystemService(Context.PRINT_SERVICE);
        if (pm == null) return;
        String job = safeTitle(title);
        PrintDocumentAdapter adapter = view.createPrintDocumentAdapter(job);
        PrintAttributes attrs = new PrintAttributes.Builder()
                .setMinMargins(PrintAttributes.Margins.NO_MARGINS)
                .build();
        pm.print(job, adapter, attrs);
    }

    /** Print a page from the server (a receipt), using the web view's sign-in cookies. Main thread only. */
    static void printUrl(Activity activity, String url, String title) {
        WebView w = offscreen(activity, title);
        w.loadUrl(url);
    }

    /** Print HTML built on the phone (an offline receipt). Main thread only. */
    static void printHtml(Activity activity, String html, String title) {
        WebView w = offscreen(activity, title);
        w.loadDataWithBaseURL("file:///android_asset/offline/", html, "text/html", "utf-8", null);
    }

    private static WebView offscreen(final Activity activity, final String title) {
        final WebView w = new WebView(activity);
        w.getSettings().setJavaScriptEnabled(false);
        w.setWebViewClient(new WebViewClient() {
            private boolean done;

            @Override
            public void onPageFinished(WebView view, String url) {
                if (done) return;
                done = true;
                printWebView(activity, view, title);  // `pending` keeps the page alive while the job prints
            }
        });
        pending = w;
        return w;
    }

    private static String safeTitle(String t) {
        String s = t == null ? "" : t.replaceAll("[^A-Za-z0-9 _.-]", " ").trim();
        return s.isEmpty() ? "TylonERP receipt" : s;
    }
}
