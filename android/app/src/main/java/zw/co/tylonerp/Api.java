package zw.co.tylonerp;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Talks to the TylonERP server's /api/v1 endpoints. Every call runs off the main thread. */
final class Api {
    static final String USER_AGENT = "TylonERP-Android/" + BuildConfig.VERSION_NAME;

    /** The server answered, but not with success. */
    static final class ApiException extends Exception {
        private static final long serialVersionUID = 1L;
        final int status;
        final boolean signedOut;

        ApiException(int status, String message, boolean signedOut) {
            super(message);
            this.status = status;
            this.signedOut = signedOut;
        }
    }

    private Api() {}

    static JSONObject get(String server, String path, String token) throws IOException, ApiException {
        return request("GET", server + path, token, null, 30000);
    }

    static JSONObject post(String server, String path, String token, JSONObject body) throws IOException, ApiException {
        return request("POST", server + path, token, body, 60000);
    }

    /** Quick check that the server is up, used before switching to the online app. */
    static boolean reachable(String server) {
        if (server == null || server.isEmpty()) return false;
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(server + "/healthz").openConnection();
            c.setConnectTimeout(5000);
            c.setReadTimeout(5000);
            c.setRequestProperty("User-Agent", USER_AGENT);
            int code = c.getResponseCode();
            return code >= 200 && code < 300;
        } catch (IOException e) {
            return false;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static JSONObject request(String method, String url, String token, JSONObject body, int readTimeout)
            throws IOException, ApiException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setRequestMethod(method);
            c.setConnectTimeout(15000);
            c.setReadTimeout(readTimeout);
            c.setUseCaches(false);
            c.setRequestProperty("Accept", "application/json");
            c.setRequestProperty("User-Agent", USER_AGENT);
            if (token != null) c.setRequestProperty("Authorization", "Bearer " + token);
            if (body != null) {
                byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                // No streaming mode: with it, some HTTP stacks drop the body of a 401 reply, losing the server's message.
                OutputStream out = c.getOutputStream();
                try {
                    out.write(bytes);
                } finally {
                    out.close();
                }
            }
            int status = c.getResponseCode();
            InputStream in = status >= 400 ? c.getErrorStream() : c.getInputStream();
            String text = in == null ? "" : readAll(in);
            JSONObject json;
            try {
                json = text.isEmpty() ? new JSONObject() : new JSONObject(text);
            } catch (JSONException e) {
                throw new ApiException(status, status == 429
                        ? "Too many attempts. Wait a minute, then try again."
                        : "The server sent an unexpected reply (" + status + "). Check the server address.", false);
            }
            if (status >= 400 || !json.optBoolean("ok", true)) {
                String msg = json.optString("error", "The server refused the request (" + status + ").");
                throw new ApiException(status, msg, status == 401 && json.optBoolean("signed_out", false));
            }
            return json;
        } finally {
            c.disconnect();
        }
    }

    private static String readAll(InputStream in) throws IOException {
        try {
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] chunk = new byte[8192];
            int n;
            while ((n = in.read(chunk)) != -1) buf.write(chunk, 0, n);
            return new String(buf.toByteArray(), StandardCharsets.UTF_8);
        } finally {
            in.close();
        }
    }
}
