package zw.co.tylonerp;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONObject;

/** Where the server is, who is signed in on this phone, and when it last synced. */
final class Prefs {
    private final SharedPreferences sp;

    Prefs(Context context) {
        sp = context.getApplicationContext().getSharedPreferences("tylonerp", Context.MODE_PRIVATE);
    }

    String server() {
        String s = sp.getString("server", null);
        return normaliseServer(s != null ? s : BuildConfig.SERVER_URL);
    }

    String slug() { return sp.getString("slug", ""); }

    String token() { return sp.getString("token", null); }

    boolean signedIn() { return token() != null; }

    /** True when the server rejected the token (password changed, account disabled): ask to sign in again. */
    boolean needsSignIn() { return sp.getBoolean("needs_sign_in", false); }

    void setNeedsSignIn(boolean v) { sp.edit().putBoolean("needs_sign_in", v).apply(); }

    JSONObject tenant() { return json(sp.getString("tenant", null)); }

    JSONObject user() { return json(sp.getString("user", null)); }

    long lastSync() { return sp.getLong("last_sync", 0L); }

    void setLastSync(long when) { sp.edit().putLong("last_sync", when).apply(); }

    void saveLogin(String server, String slug, String token, JSONObject tenant, JSONObject user) {
        sp.edit()
                .putString("server", normaliseServer(server))
                .putString("slug", slug)
                .putString("token", token)
                .putString("tenant", tenant != null ? tenant.toString() : null)
                .putString("user", user != null ? user.toString() : null)
                .putBoolean("needs_sign_in", false)
                .apply();
    }

    void saveProfile(JSONObject tenant, JSONObject user) {
        SharedPreferences.Editor e = sp.edit();
        if (tenant != null) e.putString("tenant", tenant.toString());
        if (user != null) e.putString("user", user.toString());
        e.apply();
    }

    /** Forget the account but keep the server address, so signing in again is quick. */
    void signOut() {
        sp.edit().remove("token").remove("tenant").remove("user").remove("last_sync").remove("needs_sign_in").apply();
    }

    static String normaliseServer(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.isEmpty()) return "";
        if (!s.startsWith("http://") && !s.startsWith("https://")) s = "https://" + s;
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        return s;
    }

    private static JSONObject json(String s) {
        if (s == null) return new JSONObject();
        try {
            return new JSONObject(s);
        } catch (Exception e) {
            return new JSONObject();
        }
    }
}
