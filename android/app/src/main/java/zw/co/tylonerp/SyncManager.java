package zw.co.tylonerp;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Uploads changes made on the phone and refreshes the phone's copy of the business.
 *
 * Only one sync runs at a time. Each change has its own id, so if the connection drops half way the next sync
 * simply sends the same changes again and the server answers with the result it already stored.
 */
final class SyncManager {
    interface Listener {
        void onSyncState(JSONObject state);
    }

    private static final int BATCH = 200;
    private static SyncManager instance;

    private final Context app;
    private final Store store;
    private final Prefs prefs;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final CopyOnWriteArrayList<Listener> listeners = new CopyOnWriteArrayList<>();
    private volatile String lastError;
    private volatile boolean lastFailedForNetwork;

    static synchronized SyncManager get(Context context) {
        if (instance == null) instance = new SyncManager(context.getApplicationContext());
        return instance;
    }

    private SyncManager(Context context) {
        app = context;
        store = Store.get(context);
        prefs = new Prefs(context);
    }

    void addListener(Listener l) { listeners.addIfAbsent(l); }

    void removeListener(Listener l) { listeners.remove(l); }

    boolean isRunning() { return running.get(); }

    boolean lastFailedForNetwork() { return lastFailedForNetwork; }

    /** Start a sync in the background unless one is already running. */
    void requestSync() {
        if (running.get() || !prefs.signedIn()) return;
        Thread t = new Thread(this::runSync, "tylonerp-sync");
        t.setDaemon(true);
        t.start();
    }

    /** Run a sync on the calling thread (never the main thread). Returns the state afterwards. */
    JSONObject runSync() {
        if (!prefs.signedIn() || !running.compareAndSet(false, true)) return state();
        notifyListeners();
        try {
            String server = prefs.server();
            String token = prefs.token();
            JSONObject catalog = null;
            boolean uploaded = false;
            while (true) {
                List<JSONObject> batch = store.pending(BATCH);
                if (batch.isEmpty()) break;
                int waitingBefore = store.count("pending");
                JSONObject body = new JSONObject();
                JSONArray ops = new JSONArray();
                for (JSONObject op : batch) ops.put(op);
                body.put("ops", ops);
                JSONObject resp = Api.post(server, "/api/v1/sync", token, body);
                JSONArray results = resp.optJSONArray("results");
                boolean retryLater = false;
                for (int i = 0; results != null && i < results.length(); i++) {
                    JSONObject r = results.optJSONObject(i);
                    if (r == null) continue;
                    if (r.optBoolean("retry", false)) retryLater = true;
                    store.markResult(r);
                }
                catalog = resp.optJSONObject("catalog");
                uploaded = true;
                // Stop when everything is sent, the server asked to try again later, or nothing moved (never loop).
                if (retryLater || batch.size() < BATCH || store.count("pending") >= waitingBefore) break;
            }
            if (!uploaded) catalog = Api.get(server, "/api/v1/catalog", token);
            if (catalog != null) {
                store.saveCatalog(catalog);
                prefs.saveProfile(catalog.optJSONObject("tenant"), catalog.optJSONObject("user"));
            }
            prefs.setLastSync(System.currentTimeMillis());
            lastError = null;
            lastFailedForNetwork = false;
        } catch (Api.ApiException e) {
            lastError = e.getMessage();
            lastFailedForNetwork = e.status >= 500;
            if (e.signedOut || e.status == 401) prefs.setNeedsSignIn(true);
        } catch (IOException e) {
            lastError = "No connection to the server. Your work is saved on this phone and will upload later.";
            lastFailedForNetwork = true;
        } catch (JSONException | RuntimeException e) {
            lastError = "Sync stopped: " + e.getMessage();
            lastFailedForNetwork = true;
        } finally {
            running.set(false);
        }
        if (store.count("pending") > 0) SyncJobService.scheduleUpload(app);
        JSONObject s = state();
        notifyListeners();
        return s;
    }

    JSONObject state() {
        JSONObject s = new JSONObject();
        try {
            s.put("syncing", running.get());
            s.put("pending", store.count("pending"));
            s.put("failed", store.count("failed"));
            s.put("last_sync", prefs.lastSync());
            s.put("error", lastError == null ? JSONObject.NULL : lastError);
            s.put("needs_sign_in", prefs.needsSignIn());
        } catch (JSONException ignored) {
            // constant keys
        }
        return s;
    }

    private void notifyListeners() {
        JSONObject s = state();
        for (Listener l : listeners) l.onSyncState(s);
    }
}
