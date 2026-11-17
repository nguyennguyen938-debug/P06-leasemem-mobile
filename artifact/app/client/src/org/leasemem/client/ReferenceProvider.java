package org.leasemem.client;
import android.content.*;
import android.database.Cursor;
import android.database.sqlite.*;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import org.json.*;
import java.util.UUID;
/** Cooperative reference only. Every write and managed restore uses this API. */
public class ReferenceProvider extends ContentProvider {
    SQLiteDatabase db;
    public boolean onCreate() {
        db = new SQLiteOpenHelper(getContext(), "reference.db", null, 1) {
            public void onCreate(SQLiteDatabase d) {
                d.execSQL("CREATE TABLE meta(epoch TEXT NOT NULL, rev INTEGER NOT NULL)");
                d.execSQL("INSERT INTO meta VALUES (?,0)",new Object[]{UUID.randomUUID().toString()});
                d.execSQL("CREATE TABLE facts(id INTEGER PRIMARY KEY, value TEXT NOT NULL)");
            }
            public void onUpgrade(SQLiteDatabase d,int a,int b) { throw new IllegalStateException("migration required"); }
        }.getWritableDatabase(); return true;
    }
    @Override public synchronized Bundle call(String method,String arg,Bundle extras) {
        JSONObject o=new JSONObject(); long start=SystemClock.elapsedRealtimeNanos();
        db.beginTransaction();
        try {
            if ("reset".equals(method) || "restore".equals(method)) {
                db.execSQL("DELETE FROM facts");
                // Managed restore changes epoch in the same transaction, before any snapshot can observe data.
                db.execSQL("UPDATE meta SET epoch=?,rev=0",new Object[]{UUID.randomUUID().toString()});
                if ("restore".equals(method)) db.execSQL("INSERT INTO facts VALUES (1,'A')");
            } else if ("put".equals(method)) {
                db.execSQL("INSERT OR REPLACE INTO facts VALUES (1,?)",new Object[]{arg});
                db.execSQL("UPDATE meta SET rev=rev+1");
            } else if ("delete".equals(method)) {
                db.execSQL("DELETE FROM facts WHERE id=1"); db.execSQL("UPDATE meta SET rev=rev+1");
            } else if (!"snapshot".equals(method)) throw new IllegalArgumentException(method);
            try(Cursor c=db.rawQuery("SELECT epoch,rev FROM meta",null)) { c.moveToFirst();o.put("epoch",c.getString(0));o.put("revision",c.getLong(1)); }
            JSONArray rows=new JSONArray();
            try(Cursor c=db.rawQuery("SELECT id,value FROM facts ORDER BY id",null)) { while(c.moveToNext()) rows.put(new JSONArray().put(c.getLong(0)).put(c.getString(1))); }
            o.put("rows",rows);o.put("value",rows.toString());o.put("snapshot_ns",SystemClock.elapsedRealtimeNanos());
            db.setTransactionSuccessful();
        } catch(Exception e) { throw new IllegalStateException(e); }
        finally { db.endTransaction(); }
        try {o.put("start_ns",start);o.put("end_ns",SystemClock.elapsedRealtimeNanos());}catch(Exception ignored){}
        Bundle b=new Bundle();b.putString("json",o.toString());return b;
    }
    public Cursor query(Uri u,String[] p,String s,String[] a,String o){throw new UnsupportedOperationException();}
    public String getType(Uri u){return "application/json";}
    public Uri insert(Uri u,ContentValues v){throw new UnsupportedOperationException();}
    public int delete(Uri u,String s,String[] a){throw new UnsupportedOperationException();}
    public int update(Uri u,ContentValues v,String s,String[] a){throw new UnsupportedOperationException();}
}
