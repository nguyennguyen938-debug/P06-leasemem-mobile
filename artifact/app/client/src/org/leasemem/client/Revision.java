package org.leasemem.client;
import android.content.*;
import android.net.Uri;
import android.os.*;
import android.provider.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.util.*;

/** Revision protocol. Test helper is loopback-only and deliberately instrumented. */
public final class Revision {
    static final Uri REF=Uri.parse("content://org.leasemem.reference");
    static long ns(){return SystemClock.elapsedRealtimeNanos();}
    static JSONObject ref(LmApp a,String method,String value)throws Exception {
        return new JSONObject(a.cr.call(REF,method,value,null).getString("json"));
    }
    static String token(JSONObject x)throws Exception{return x.getString("epoch")+":"+x.getLong("revision");}
    static JSONObject observe(LmApp a,String fid)throws Exception {
        long t=ns(); LmApp.Res r=a.read(fid);
        JSONObject o=new JSONObject();o.put("schema",4);o.put("query_definition","LmApp.read/v4:"+fid);o.put("fact",fid);o.put("source",LmApp.srcOf(fid));
        o.put("value",r.val);o.put("support",new JSONArray(r.ids));o.put("read_start_ns",t);o.put("read_end_ns",ns());
        o.put("contract","stock-query-no-certified-snapshot");o.put("verdict","UNKNOWN");
        o.put("reason",r.val!=null&&r.val.startsWith("ERR:")?"query_error":"strict_epoch_and_snapshot_unavailable");
        return o;
    }
    static JSONObject validate(LmApp a,String fid,JSONObject cert)throws Exception {
        JSONObject v=new JSONObject();v.put("verdict","UNKNOWN");
        v.put("reason",cert==null||cert.optInt("schema")!=4?"legacy_or_missing_certificate":"strict_epoch_and_snapshot_unavailable");
        v.put("fact",fid);v.put("start_ns",ns());v.put("end_ns",ns());return v;
    }
    static JSONObject bracket(LmApp a,String inject,boolean anchor,JSONObject old)throws Exception {
        JSONArray attempts=new JSONArray();JSONObject result=new JSONObject();
        for(int i=0;i<3;i++) {
            JSONObject before=ref(a,"snapshot",null);
            if(i==0 && inject.equals("before_query"))ref(a,"put","B-before");
            JSONObject query=ref(a,"snapshot",null); // value and complete support from one actual transaction
            if((i==0 && inject.equals("once")) || inject.equals("every")) ref(a,"put","B"+i);
            JSONObject support=ref(a,"snapshot",null);
            if(i==0 && inject.equals("support"))ref(a,"put","B-support");
            JSONObject delta=ref(a,"snapshot",null); // full reference snapshot supplies complete changes by comparison
            if(i==0 && inject.equals("delta"))ref(a,"put","B-delta");
            JSONObject after=ref(a,"snapshot",null);
            JSONObject attempt=new JSONObject();attempt.put("before",before);attempt.put("query",query);attempt.put("support",support);attempt.put("delta",delta);attempt.put("after",after);attempts.put(attempt);
            if(token(before).equals(token(after))) {
                result.put("certificate",query);result.put("certified_ns",query.getLong("snapshot_ns"));
                result.put("verdict",anchor?"FRESH":old==null?"UNKNOWN":!old.getString("epoch").equals(query.getString("epoch"))?"UNKNOWN":old.getString("value").equals(query.getString("value"))?"FRESH":"CHANGED");
                result.put("reason",anchor?"atomic_value_anchor":"stable_complete_evidence");break;
            }
        }
        if(!result.has("verdict")){result.put("verdict","UNKNOWN");result.put("reason","retry_exhausted");}
        result.put("attempts",attempts);return result;
    }
    static JSONObject referenceTrial(LmApp a,String scenario)throws Exception {
        ref(a,"reset",null); JSONObject original=ref(a,"put","A");JSONObject o=new JSONObject();o.put("scenario",scenario);o.put("old",original);
        if(scenario.equals("observation")||scenario.equals("reanchor")) {
            JSONObject q=ref(a,"snapshot",null);ref(a,"put","B");JSONObject w=ref(a,"snapshot",null);
            o.put("historical_value",q.getString("value"));o.put("historical_stamp",w);o.put("historical_verdict","FRESH");o.put("truth",ref(a,"snapshot",null));
            ref(a,"put","A");o.put("repaired",bracket(a,"once",true,null));
        } else if(scenario.equals("concurrent")||scenario.equals("exhaust")||scenario.equals("before_query")||scenario.equals("support")||scenario.equals("delta")) {
            o.put("repaired",bracket(a,scenario.equals("exhaust")?"every":scenario.equals("concurrent")?"once":scenario,false,original));
        } else {
            if(scenario.equals("delete")) ref(a,"delete",null);
            if(scenario.equals("reuse")) {ref(a,"delete",null);ref(a,"put","B");}
            if(scenario.equals("reset")) {ref(a,"reset",null);ref(a,"put","A");}
            if(scenario.equals("restore")) {ref(a,"put","B");ref(a,"restore",null);}
            if(scenario.equals("aba")) {ref(a,"put","B");ref(a,"put","A");}
            o.put("repaired",bracket(a,"none",false,original));
        }
        if(scenario.equals("action")) {
            JSONObject v=o.getJSONObject("repaired");String used=v.getJSONObject("certificate").getString("value");
            JSONObject mutation=ref(a,"put","B-after-check");ContentValues effect=new ContentValues();
            effect.put(CallLog.Calls.NUMBER,"+1666-reference-A");effect.put(CallLog.Calls.TYPE,CallLog.Calls.OUTGOING_TYPE);effect.put(CallLog.Calls.DATE,System.currentTimeMillis());effect.put(CallLog.Calls.DURATION,0);
            long t=ns();Uri uri=a.cr.insert(CallLog.Calls.CONTENT_URI,effect);o.put("effect_start_ns",t);o.put("effect_end_ns",ns());o.put("effect_uri",String.valueOf(uri));o.put("used",used);o.put("mutation_after_check",mutation);o.put("truth_after",ref(a,"snapshot",null));
        }
        return o;
    }
    static JSONObject mutateOther(LmApp a,String src,String kind)throws Exception {
        String id="rev"+ns();Intent it=new Intent();it.setComponent(new ComponentName("org.leasemem.mut","org.leasemem.mut.Cmd"));
        it.putExtra("op","mutate");it.putExtra("a",src);it.putExtra("b",kind);it.putExtra("tag",id);it.putExtra("id",id);it.addFlags(32);a.sendBroadcast(it);
        // Host-side barrier retrieves writer output; the client cannot read another application's private files.
        JSONObject o=new JSONObject();o.put("writer_id",id);return o;
    }
    static Map<String,Map<String,JSONObject>> caches=new LinkedHashMap<>();
    static JSONObject batch(LmApp a,String mode)throws Exception {
        Map<String,JSONObject> cache=caches.get(mode);if(cache==null){cache=new LinkedHashMap<>();caches.put(mode,cache);}
        long start=ns();JSONObject values=new JSONObject(),verdicts=new JSONObject();int refreshed=0,queries=0;
        boolean epochBroken=!cache.containsKey("__epoch")||!a.epoch.equals(cache.get("__epoch").optString("value"));
        for(String[] f:LmApp.FACTS) {
            String fid=f[0];JSONObject old=cache.get(fid); boolean refresh=true;
            if(mode.equals("relay")&&old!=null&&!epochBroken) refresh=a.obj("ev_dirty").optBoolean(f[1]);
            if(mode.equals("validate")) verdicts.put(fid,validate(a,fid,old));
            if(refresh||old==null) {JSONObject n=observe(a,fid);values.put(fid,n.get("value"));cache.put(fid,n);refreshed++;queries++;}
            else values.put(fid,old.optString("value"));
        }
        JSONObject ep=new JSONObject();ep.put("value",a.epoch);cache.put("__epoch",ep);
        JSONObject o=new JSONObject();o.put("mode",mode);o.put("values",values);o.put("verdicts",verdicts);o.put("refreshes",refreshed);o.put("fact_reads",queries);o.put("start_ns",start);o.put("end_ns",ns());o.put("epoch",a.epoch);
        // Never clear notifications here: a callback racing this batch must not be erased.
        return o;
    }
    static JSONObject stockEvidence(LmApp a,String src)throws Exception {
        JSONObject o=new JSONObject();o.put("start_ns",ns());o.put("watermark",a.watermark(src));
        if(src.equals("contacts"))o.put("complete_version_map",a.verMap());
        if(src.equals("calllog"))o.put("rows",new JSONArray(a.q(CallLog.Calls.CONTENT_URI,new String[]{"_id","number","type","date","last_modified"},"number LIKE '+1666%'",null,"_id")));
        if(src.equals("media"))o.put("rows",new JSONArray(a.q(MediaStore.Images.Media.getContentUri(LmApp.VOL),new String[]{"_id","_display_name","generation_modified"},"relative_path='Pictures/lm/'",null,"_id")));
        JSONObject vals=new JSONObject();for(String[] f:LmApp.FACTS)if(f[1].equals(src))vals.put(f[0],a.read(f[0]).val);
        o.put("values",vals);o.put("end_ns",ns());o.put("certified",false);return o;
    }
    static JSONObject tick(LmApp a)throws Exception {
        JSONObject o=new JSONObject();JSONArray pairs=new JSONArray();
        java.util.List<String[]> rows=a.q(CallLog.Calls.CONTENT_URI,new String[]{"_id"},"number LIKE '+1666%'",null,"_id");
        if(rows.isEmpty())throw new IllegalStateException("no fixture calls");
        Uri u=android.content.ContentUris.withAppendedId(CallLog.Calls.CONTENT_URI,Long.parseLong(rows.get(0)[0]));
        for(int i=0;i<100;i++) {
            ContentValues v=new ContentValues();v.put("number","+1666A"+i);a.cr.update(u,v,null,null);
            String before=a.one(u,"last_modified",null);String valueBefore=a.one(u,"number",null);
            v.put("number","+1666B"+i);a.cr.update(u,v,null,null);
            String after=a.one(u,"last_modified",null);String valueAfter=a.one(u,"number",null);
            JSONObject pair=new JSONObject();pair.put("before",before);pair.put("after",after);pair.put("value_before",valueBefore);pair.put("value_after",valueAfter);pairs.put(pair);
            if(before.equals(after)&&!valueBefore.equals(valueAfter))break;
        }
        o.put("pairs",pairs);o.put("strict_verdict","UNKNOWN");return o;
    }
    static JSONObject handle(LmApp a,JSONObject r)throws Exception {
        String op=r.getString("op");
        if(op.equals("stock_evidence"))return stockEvidence(a,r.getString("source"));
        if(op.equals("tick"))return tick(a);
        if(op.equals("reference"))return referenceTrial(a,r.getString("scenario"));
        if(op.equals("refcall"))return ref(a,r.getString("method"),r.optString("value",null));
        if(op.equals("batch"))return batch(a,r.getString("mode"));
        if(op.equals("read")){JSONObject o=observe(a,r.getString("fact"));try{o.put("watermark",a.watermark(LmApp.srcOf(r.getString("fact"))));}catch(Exception e){o.put("watermark_error",e.toString());}return o;}
        if(op.equals("probe"))return a.probe();
        if(op.equals("resetcache")){caches.clear();a.mem.put("ev_dirty",new JSONObject());return new JSONObject().put("ok",true);}
        if(op.equals("anchor")){JSONObject out=new JSONObject();a.observe(out);return out;}
        if(op.equals("validate"))return validate(a,r.getString("fact"),r.optJSONObject("certificate"));
        if(op.equals("historical_validate")) {JSONObject cost=new JSONObject();Map<String,String> v=a.lmValidateHistorical(new HashSet<>(Arrays.asList(LmApp.SOURCES)),true,cost);return new JSONObject().put("verdicts",new JSONObject(v)).put("cost",cost);}
        if(op.equals("install_historical_anchor")){a.observeHistorical(new JSONObject());return new JSONObject().put("ok",true);}
        if(op.equals("overwrite_historical_wm")){JSONObject wm=a.mem.getJSONObject("wm");String src=r.getString("source");wm.put(LmApp.wmKey(src,a.rule(src)),a.watermark(src));a.mem.put("ver_map",a.verMap());return new JSONObject().put("ok",true);}
        if(op.equals("state")){JSONObject o=new JSONObject();o.put("epoch",a.epoch);o.put("events",a.mem.opt("events"));o.put("dirty",a.obj("ev_dirty"));o.put("fg",FgService.running);o.put("pid",android.os.Process.myPid());return o;}
        throw new IllegalArgumentException(op);
    }
    static void start(LmApp a) {
        new Thread(()->{try(ServerSocket server=new ServerSocket(8766,20,InetAddress.getByName("127.0.0.1"))) {
            while(true) {try(Socket s=server.accept()) {s.setSoTimeout(60000);BufferedReader in=new BufferedReader(new InputStreamReader(s.getInputStream(),"UTF-8"));PrintWriter out=new PrintWriter(new OutputStreamWriter(s.getOutputStream(),"UTF-8"),true);String line;
                while((line=in.readLine())!=null){JSONObject response;try{response=handle(a,new JSONObject(line));}catch(Exception e){response=new JSONObject();try{response.put("error",e.toString());}catch(Exception ignored){}}out.println(response);}
            }catch(Exception e){android.util.Log.e("REVISION","client",e);}}
        }catch(Exception e){android.util.Log.e("REVISION","server",e);}},"revision-loopback").start();
    }
}
