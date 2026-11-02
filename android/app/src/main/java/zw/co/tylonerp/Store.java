package zw.co.tylonerp;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * The phone's own copy of the business: products, clients and open debts from the server, plus every change made
 * on the phone that is still waiting to be uploaded ("ops").
 *
 * Records the phone created offline have ids "l:op-id"; records from the server have ids "s:server-id". A change
 * refers to records by these ids, and the server works out which real record each one became.
 *
 * Every change is applied to the local copy straight away, so the offline screens show the right stock. After a
 * sync, the server's copy replaces the local one and any changes still waiting are applied on top again.
 */
final class Store extends SQLiteOpenHelper {
    private static final int VERSION = 1;
    private static Store instance;

    static synchronized Store get(Context context) {
        if (instance == null) instance = new Store(context.getApplicationContext());
        return instance;
    }

    private Store(Context context) {
        super(context, "tylonerp.db", null, VERSION);
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE products (id TEXT PRIMARY KEY, name TEXT NOT NULL, price TEXT NOT NULL, stock INTEGER NOT NULL,"
                + " barcode TEXT, sku TEXT, reorder INTEGER NOT NULL DEFAULT 5)");
        db.execSQL("CREATE TABLE clients (id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT)");
        db.execSQL("CREATE TABLE debts (id TEXT PRIMARY KEY, client_id TEXT, client TEXT, product TEXT, quantity INTEGER,"
                + " total TEXT, balance TEXT, created_at TEXT, local INTEGER NOT NULL DEFAULT 0)");
        db.execSQL("CREATE TABLE ops (seq INTEGER PRIMARY KEY AUTOINCREMENT, op_id TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,"
                + " data TEXT NOT NULL, summary TEXT, created_at INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending',"
                + " error TEXT, warning TEXT, attempts INTEGER NOT NULL DEFAULT 0)");
        db.execSQL("CREATE INDEX ops_status ON ops (status, seq)");
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // Version 1 is the first schema; later versions add their migrations here. Never drop "ops": it holds
        // work that has not reached the server yet.
    }

    // ------------------------------------------------------------------ reading

    synchronized JSONArray products() {
        JSONArray out = new JSONArray();
        Cursor c = getReadableDatabase().rawQuery(
                "SELECT id, name, price, stock, barcode, sku, reorder FROM products ORDER BY name COLLATE NOCASE", null);
        try {
            while (c.moveToNext()) {
                JSONObject p = new JSONObject();
                put(p, "id", c.getString(0));
                put(p, "name", c.getString(1));
                put(p, "price", c.getString(2));
                put(p, "stock", c.getInt(3));
                put(p, "barcode", c.isNull(4) ? JSONObject.NULL : c.getString(4));
                put(p, "sku", c.isNull(5) ? JSONObject.NULL : c.getString(5));
                put(p, "reorder_level", c.getInt(6));
                out.put(p);
            }
        } finally {
            c.close();
        }
        return out;
    }

    synchronized JSONArray clients() {
        JSONArray out = new JSONArray();
        Cursor c = getReadableDatabase().rawQuery("SELECT id, name, phone FROM clients ORDER BY name COLLATE NOCASE", null);
        try {
            while (c.moveToNext()) {
                JSONObject o = new JSONObject();
                put(o, "id", c.getString(0));
                put(o, "name", c.getString(1));
                put(o, "phone", c.isNull(2) ? JSONObject.NULL : c.getString(2));
                out.put(o);
            }
        } finally {
            c.close();
        }
        return out;
    }

    synchronized JSONArray debts() {
        JSONArray out = new JSONArray();
        Cursor c = getReadableDatabase().rawQuery("SELECT id, client_id, client, product, quantity, total, balance, created_at, local"
                + " FROM debts WHERE CAST(balance AS REAL) > 0 ORDER BY created_at", null);
        try {
            while (c.moveToNext()) {
                JSONObject o = new JSONObject();
                put(o, "id", c.getString(0));
                put(o, "client_id", c.getString(1));
                put(o, "client", c.getString(2));
                put(o, "product", c.getString(3));
                put(o, "quantity", c.getInt(4));
                put(o, "total", c.getString(5));
                put(o, "balance", c.getString(6));
                put(o, "created_at", c.getString(7));
                put(o, "local", c.getInt(8) == 1);
                out.put(o);
            }
        } finally {
            c.close();
        }
        return out;
    }

    /** The most recent changes made on this phone, newest first, with what happened to each. */
    synchronized JSONArray ops(int limit) {
        JSONArray out = new JSONArray();
        Cursor c = getReadableDatabase().rawQuery("SELECT op_id, kind, summary, created_at, status, error, warning FROM ops"
                + " ORDER BY seq DESC LIMIT " + limit, null);
        try {
            while (c.moveToNext()) {
                JSONObject o = new JSONObject();
                put(o, "op_id", c.getString(0));
                put(o, "kind", c.getString(1));
                put(o, "summary", c.getString(2));
                put(o, "created_at", c.getLong(3));
                put(o, "status", c.getString(4));
                put(o, "error", c.isNull(5) ? JSONObject.NULL : c.getString(5));
                put(o, "warning", c.isNull(6) ? JSONObject.NULL : c.getString(6));
                out.put(o);
            }
        } finally {
            c.close();
        }
        return out;
    }

    synchronized int count(String status) {
        Cursor c = getReadableDatabase().rawQuery("SELECT COUNT(*) FROM ops WHERE status = ?", new String[]{status});
        try {
            return c.moveToFirst() ? c.getInt(0) : 0;
        } finally {
            c.close();
        }
    }

    /** Changes waiting to be uploaded, oldest first, in the shape the server expects. */
    synchronized List<JSONObject> pending(int limit) {
        List<JSONObject> out = new ArrayList<>();
        Cursor c = getReadableDatabase().rawQuery("SELECT op_id, kind, data FROM ops WHERE status = 'pending' ORDER BY seq LIMIT " + limit, null);
        try {
            while (c.moveToNext()) {
                JSONObject o = new JSONObject();
                put(o, "op_id", c.getString(0));
                put(o, "kind", c.getString(1));
                try {
                    o.put("data", new JSONObject(c.getString(2)));
                } catch (JSONException e) {
                    put(o, "data", new JSONObject());
                }
                out.add(o);
            }
        } finally {
            c.close();
        }
        return out;
    }

    // ------------------------------------------------------------------ recording a change

    /**
     * Record a change made on the phone and apply it to the local copy. Returns {ok, op_id} or {ok:false, error}.
     * Checks here mirror the server's, so a change that cannot work is refused now rather than failing later.
     */
    synchronized JSONObject queue(String kind, JSONObject data, String summary) {
        JSONObject res = new JSONObject();
        String error = validate(kind, data);
        if (error != null) {
            put(res, "ok", false);
            put(res, "error", error);
            return res;
        }
        String opId = UUID.randomUUID().toString();
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            applyLocal(db, kind, data, opId);
            ContentValues v = new ContentValues();
            v.put("op_id", opId);
            v.put("kind", kind);
            v.put("data", data.toString());
            v.put("summary", summary);
            v.put("created_at", System.currentTimeMillis());
            v.put("status", "pending");
            db.insertOrThrow("ops", null, v);
            db.setTransactionSuccessful();
        } catch (RuntimeException e) {
            put(res, "ok", false);
            put(res, "error", "Could not save that on the phone: " + e.getMessage());
            return res;
        } finally {
            db.endTransaction();
        }
        put(res, "ok", true);
        put(res, "op_id", opId);
        put(res, "id", "l:" + opId);
        return res;
    }

    private String validate(String kind, JSONObject d) {
        switch (kind) {
            case "client.create":
                return d.optString("name").trim().isEmpty() ? "Enter the client's name." : null;
            case "product.create": {
                if (d.optString("name").trim().isEmpty()) return "Enter the product name.";
                if (money(d.optString("price")) == null) return "Enter a valid price.";
                if (d.optInt("stock", 0) < 0) return "Quantity cannot be negative.";
                String code = d.optString("barcode", "");
                if (!code.isEmpty() && productByBarcode(code) != null) return "That barcode is already registered.";
                if (productIdByName(d.optString("name")) != null) return "A product with that name is already registered. Add stock to it instead.";
                return null;
            }
            case "stock.add":
                if (d.optInt("quantity", 0) <= 0) return "Enter a quantity above zero.";
                return productExists(d.optString("product")) ? null : "That product is not on this phone.";
            case "sale.create": {
                String pid = d.optString("product");
                int qty = d.optInt("quantity", 0);
                if (!productExists(pid)) return "That product is not on this phone.";
                if (qty <= 0) return "Enter how many to sell.";
                int stock = productStock(pid);
                if (qty > stock) return "Only " + stock + " left in stock on this phone.";
                BigDecimal unit = money(d.optString("unit_price"));
                if (unit == null) return "The price is not valid.";
                BigDecimal total = unit.multiply(BigDecimal.valueOf(qty));
                String paidRaw = d.optString("paid", "").trim();
                BigDecimal paid = paidRaw.isEmpty() ? total : money(paidRaw);
                if (paid == null) return "The amount paid is not valid.";
                if (paid.compareTo(total) < 0 && d.optString("client").isEmpty()) return "Choose a client for a part-paid or credit sale.";
                if ("onemoney".equals(d.optString("method"))) {
                    String phone = d.optString("phone").replaceAll("\\D", "");
                    if (phone.startsWith("263")) phone = phone.substring(3);
                    if (phone.startsWith("0")) phone = phone.substring(1);
                    if (!phone.matches("71\\d{7}")) return "Enter the customer's OneMoney number, for example 0711234567.";
                    if (d.optString("payment_ref").trim().isEmpty()) return "Enter the OneMoney transaction code.";
                }
                return null;
            }
            case "payment.create": {
                BigDecimal amount = money(d.optString("amount"));
                if (amount == null || amount.signum() <= 0) return "Enter an amount above zero.";
                BigDecimal balance = debtBalance(d.optString("sale"));
                if (balance == null) return "That debt is not on this phone.";
                if (amount.compareTo(balance) > 0) return "Enter an amount up to " + balance.toPlainString() + ".";
                return null;
            }
            default:
                return "Unknown change.";
        }
    }

    /** Apply a change to the local copy. Also used to re-apply waiting changes after a fresh catalog arrives. */
    private void applyLocal(SQLiteDatabase db, String kind, JSONObject d, String opId) {
        switch (kind) {
            case "client.create": {
                ContentValues v = new ContentValues();
                v.put("id", "l:" + opId);
                v.put("name", d.optString("name").trim());
                v.put("phone", d.optString("phone", ""));
                db.insertWithOnConflict("clients", null, v, SQLiteDatabase.CONFLICT_REPLACE);
                break;
            }
            case "product.create": {
                ContentValues v = new ContentValues();
                v.put("id", "l:" + opId);
                v.put("name", d.optString("name").trim());
                BigDecimal price = money(d.optString("price"));
                v.put("price", price == null ? "0.00" : price.toPlainString());
                v.put("stock", Math.max(0, d.optInt("stock", 0)));
                String code = d.optString("barcode", "");
                if (!code.isEmpty()) v.put("barcode", code);
                v.put("sku", d.optString("sku", ""));
                v.put("reorder", d.optInt("reorder_level", 5));
                db.insertWithOnConflict("products", null, v, SQLiteDatabase.CONFLICT_REPLACE);
                break;
            }
            case "stock.add": {
                String pid = d.optString("product");
                db.execSQL("UPDATE products SET stock = stock + ? WHERE id = ?", new Object[]{d.optInt("quantity", 0), pid});
                String code = d.optString("barcode", "");
                if (!code.isEmpty()) db.execSQL("UPDATE products SET barcode = ? WHERE id = ? AND (barcode IS NULL OR barcode = '')", new Object[]{code, pid});
                break;
            }
            case "sale.create": {
                String pid = d.optString("product");
                int qty = d.optInt("quantity", 0);
                db.execSQL("UPDATE products SET stock = stock - ? WHERE id = ?", new Object[]{qty, pid});
                BigDecimal unit = money(d.optString("unit_price"));
                if (unit == null) break;
                BigDecimal total = unit.multiply(BigDecimal.valueOf(qty)).setScale(2, RoundingMode.HALF_UP);
                String paidRaw = d.optString("paid", "").trim();
                BigDecimal paid = paidRaw.isEmpty() ? total : money(paidRaw);
                String client = d.optString("client", "");
                if (paid != null && paid.compareTo(total) < 0 && !client.isEmpty()) {
                    ContentValues v = new ContentValues();
                    v.put("id", "l:" + opId);
                    v.put("client_id", client);
                    v.put("client", clientName(db, client));
                    v.put("product", productName(db, pid));
                    v.put("quantity", qty);
                    v.put("total", total.toPlainString());
                    v.put("balance", total.subtract(paid).setScale(2, RoundingMode.HALF_UP).toPlainString());
                    v.put("created_at", String.valueOf(System.currentTimeMillis()));
                    v.put("local", 1);
                    db.insertWithOnConflict("debts", null, v, SQLiteDatabase.CONFLICT_REPLACE);
                }
                break;
            }
            case "payment.create": {
                String sid = d.optString("sale");
                BigDecimal amount = money(d.optString("amount"));
                BigDecimal balance = debtBalance(db, sid);
                if (amount != null && balance != null) {
                    BigDecimal left = balance.subtract(amount).max(BigDecimal.ZERO).setScale(2, RoundingMode.HALF_UP);
                    db.execSQL("UPDATE debts SET balance = ? WHERE id = ?", new Object[]{left.toPlainString(), sid});
                }
                break;
            }
            default:
                break;
        }
    }

    // ------------------------------------------------------------------ after a sync

    /** Store what the server said about an uploaded change. */
    synchronized void markResult(JSONObject result) {
        String opId = result.optString("op_id");
        if (opId.isEmpty()) return;
        ContentValues v = new ContentValues();
        if (result.optBoolean("retry", false)) {
            getWritableDatabase().execSQL("UPDATE ops SET attempts = attempts + 1, error = ? WHERE op_id = ?",
                    new Object[]{result.optString("error", null), opId});
            return;
        }
        v.put("status", result.optBoolean("ok", false) ? "done" : "failed");
        v.put("error", result.optBoolean("ok", false) ? null : result.optString("error", "The server refused this change."));
        String warning = result.optString("warning", "");
        v.put("warning", warning.isEmpty() ? null : warning);
        getWritableDatabase().update("ops", v, "op_id = ?", new String[]{opId});
    }

    /** Replace the local copy with the server's, then re-apply the changes still waiting to be uploaded. */
    synchronized void saveCatalog(JSONObject cat) {
        SQLiteDatabase db = getWritableDatabase();
        db.beginTransaction();
        try {
            db.delete("products", null, null);
            db.delete("clients", null, null);
            db.delete("debts", null, null);
            JSONArray ps = cat.optJSONArray("products");
            for (int i = 0; ps != null && i < ps.length(); i++) {
                JSONObject p = ps.optJSONObject(i);
                if (p == null) continue;
                ContentValues v = new ContentValues();
                v.put("id", "s:" + p.optLong("id"));
                v.put("name", p.optString("name"));
                v.put("price", p.optString("price", "0.00"));
                v.put("stock", p.optInt("stock", 0));
                if (!p.isNull("barcode")) v.put("barcode", p.optString("barcode"));
                if (!p.isNull("sku")) v.put("sku", p.optString("sku"));
                v.put("reorder", p.optInt("reorder_level", 5));
                db.insertWithOnConflict("products", null, v, SQLiteDatabase.CONFLICT_REPLACE);
            }
            JSONArray cs = cat.optJSONArray("clients");
            for (int i = 0; cs != null && i < cs.length(); i++) {
                JSONObject o = cs.optJSONObject(i);
                if (o == null) continue;
                ContentValues v = new ContentValues();
                v.put("id", "s:" + o.optLong("id"));
                v.put("name", o.optString("name"));
                if (!o.isNull("phone")) v.put("phone", o.optString("phone"));
                db.insertWithOnConflict("clients", null, v, SQLiteDatabase.CONFLICT_REPLACE);
            }
            JSONArray ds = cat.optJSONArray("debts");
            for (int i = 0; ds != null && i < ds.length(); i++) {
                JSONObject o = ds.optJSONObject(i);
                if (o == null) continue;
                ContentValues v = new ContentValues();
                v.put("id", "s:" + o.optLong("id"));
                v.put("client_id", "s:" + o.optLong("client_id"));
                v.put("client", o.optString("client"));
                v.put("product", o.optString("product"));
                v.put("quantity", o.optInt("quantity"));
                v.put("total", o.optString("total"));
                v.put("balance", o.optString("balance"));
                v.put("created_at", o.optString("created_at"));
                v.put("local", 0);
                db.insertWithOnConflict("debts", null, v, SQLiteDatabase.CONFLICT_REPLACE);
            }
            Cursor c = db.rawQuery("SELECT op_id, kind, data FROM ops WHERE status = 'pending' ORDER BY seq", null);
            try {
                while (c.moveToNext()) {
                    try {
                        applyLocal(db, c.getString(1), new JSONObject(c.getString(2)), c.getString(0));
                    } catch (JSONException ignored) {
                        // a damaged record cannot be re-applied; the server copy stays as it is
                    }
                }
            } finally {
                c.close();
            }
            // Keep the history of finished changes short.
            db.execSQL("DELETE FROM ops WHERE status = 'done' AND seq NOT IN (SELECT seq FROM ops WHERE status = 'done' ORDER BY seq DESC LIMIT 300)");
            db.setTransactionSuccessful();
        } finally {
            db.endTransaction();
        }
    }

    synchronized void dismiss(String opId) {
        getWritableDatabase().delete("ops", "op_id = ? AND status = 'failed'", new String[]{opId});
    }

    /** Forget everything on this phone (used when signing out after all work has been uploaded). */
    synchronized void clearAll() {
        SQLiteDatabase db = getWritableDatabase();
        db.delete("products", null, null);
        db.delete("clients", null, null);
        db.delete("debts", null, null);
        db.delete("ops", null, null);
    }

    // ------------------------------------------------------------------ helpers

    static BigDecimal money(String raw) {
        if (raw == null) return null;
        String s = raw.trim();
        if (s.isEmpty() || !s.matches("\\d{1,10}(\\.\\d{0,2})?|\\.\\d{1,2}")) return null;
        try {
            return new BigDecimal(s).setScale(2, RoundingMode.HALF_UP);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /** Same rule as the server: numeric codes match however many leading zeros they were read with. */
    static String barcodeKey(String code) {
        if (code == null) return null;
        String c = code.replaceAll("[\\x00-\\x1f\\x7f\\s]+", "").replaceFirst("^\\][A-Za-z][0-9A-Za-z]", "");
        if (c.isEmpty()) return null;
        if (!c.matches("\\d+")) return c;
        String core = c.replaceFirst("^0+", "");
        if (core.isEmpty()) core = "0";
        StringBuilder b = new StringBuilder();
        for (int i = core.length(); i < 14; i++) b.append('0');
        return b.append(core).toString();
    }

    private String productByBarcode(String code) {
        String key = barcodeKey(code);
        if (key == null) return null;
        Cursor c = getReadableDatabase().rawQuery("SELECT id, barcode FROM products WHERE barcode IS NOT NULL AND barcode != ''", null);
        try {
            while (c.moveToNext()) {
                if (key.equals(barcodeKey(c.getString(1)))) return c.getString(0);
            }
        } finally {
            c.close();
        }
        return null;
    }

    private String productIdByName(String name) {
        String n = name == null ? "" : name.trim().replaceAll("\\s+", " ").toLowerCase();
        Cursor c = getReadableDatabase().rawQuery("SELECT id, name FROM products", null);
        try {
            while (c.moveToNext()) {
                if (c.getString(1).trim().replaceAll("\\s+", " ").toLowerCase().equals(n)) return c.getString(0);
            }
        } finally {
            c.close();
        }
        return null;
    }

    private boolean productExists(String id) {
        Cursor c = getReadableDatabase().rawQuery("SELECT 1 FROM products WHERE id = ?", new String[]{id});
        try {
            return c.moveToFirst();
        } finally {
            c.close();
        }
    }

    private int productStock(String id) {
        Cursor c = getReadableDatabase().rawQuery("SELECT stock FROM products WHERE id = ?", new String[]{id});
        try {
            return c.moveToFirst() ? c.getInt(0) : 0;
        } finally {
            c.close();
        }
    }

    private BigDecimal debtBalance(String id) {
        return debtBalance(getReadableDatabase(), id);
    }

    private static BigDecimal debtBalance(SQLiteDatabase db, String id) {
        Cursor c = db.rawQuery("SELECT balance FROM debts WHERE id = ? AND local = 0", new String[]{id});
        try {
            return c.moveToFirst() ? money(c.getString(0)) : null;
        } finally {
            c.close();
        }
    }

    private static String productName(SQLiteDatabase db, String id) {
        Cursor c = db.rawQuery("SELECT name FROM products WHERE id = ?", new String[]{id});
        try {
            return c.moveToFirst() ? c.getString(0) : "";
        } finally {
            c.close();
        }
    }

    private static String clientName(SQLiteDatabase db, String id) {
        Cursor c = db.rawQuery("SELECT name FROM clients WHERE id = ?", new String[]{id});
        try {
            return c.moveToFirst() ? c.getString(0) : "";
        } finally {
            c.close();
        }
    }

    private static void put(JSONObject o, String k, Object v) {
        try {
            o.put(k, v);
        } catch (JSONException ignored) {
            // keys are constants; this cannot fail
        }
    }
}
