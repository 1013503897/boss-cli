/*
 * BOSS直聘 search request full capture (frida-17 / bundled java-bridge).
 * Correlates net.bosszhipin.base.m.{c,e,f} (real URL, thread-local) with
 * com.twl.signer.a.{i=sig, d=sp, e=encodeRequestBody(plaintext body), g/h=decode},
 * and best-effort dumps the final okhttp3 Request (url/method/headers/body).
 * Untruncated for the batch/search endpoint so the off-device pipeline can be locked.
 *
 * Build: frida-compile boss_capture.js -o boss_capture.c.js
 * Run:   python boss_frida_run.py <PID> boss_capture.c.js
 */
import Java from 'frida-java-bridge';

var HOT = ['/api/batch/requests', 'search/cardlist', 'zpgeek', 'subReqs'];
function hot(s){ if(s==null) return false; s=''+s; for(var i=0;i<HOT.length;i++) if(s.indexOf(HOT[i])>=0) return true; return false; }
var curUrl = {};
function tid(){ return Process.getCurrentThreadId(); }

Java.perform(function () {
  // ---- URL thread-label ----
  try {
    var M = Java.use('net.bosszhipin.base.m');
    M.e.implementation = function (b, url, z) { curUrl[tid()]=''+url; try { return this.e(b,url,z);} finally { delete curUrl[tid()]; } };
    M.f.implementation = function (b, url, z) { curUrl[tid()]=''+url; try { return this.f(b,url,z);} finally { delete curUrl[tid()]; } };
    send({tag:'INFO', msg:'m.e/m.f hooked'});
  } catch(e){ send({tag:'ERR', where:'m', err:''+e}); }

  // ---- signer primitives (untruncated for hot endpoints) ----
  try {
    var A = Java.use('com.twl.signer.a');
    A.i.overload('java.lang.String','java.lang.String').implementation = function (s, k) {
      var r = this.i(s,k); var u = curUrl[tid()];
      if (hot(u) || hot(s)) send({tag:'SIG', url:u||null, signedInput:''+s, key:(k==null?null:''+k), sig:''+r});
      return r;
    };
    A.d.overload('java.lang.String','java.lang.String').implementation = function (s, k) {
      var r = this.d(s,k); var u = curUrl[tid()];
      if (hot(u)) send({tag:'SP', url:u||null, strD:''+s, key:(k==null?null:''+k), sp:''+r});
      return r;
    };
    // a.e(plaintext batch body, key) -> nativeEncodeRequestBody
    A.e.overload('java.lang.String','java.lang.String').implementation = function (s, k) {
      var r = this.e(s,k); var u = curUrl[tid()];
      if (hot(u) || hot(s)) send({tag:'BODY', url:u||null, bodyPlain:''+s, key:(k==null?null:''+k)});
      return r;
    };
    send({tag:'READY', msg:'signer a.i/a.d/a.e hooked'});
  } catch(e){ send({tag:'ERR', where:'signer', err:''+e}); }

  // ---- best-effort okhttp3 Request capture (headers don't need okio) ----
  // resolve okio.Buffer (BOSS may shade okio) for optional body bytes
  var Buf = null;
  try { Buf = Java.use('okio.Buffer'); } catch(e){}
  if (Buf == null) {
    try {
      Java.enumerateLoadedClassesSync().forEach(function(n){
        if (Buf==null && /(^|\.)okio\.Buffer$|okio\d*\.Buffer$/.test(n)) { try { Buf = Java.use(n); } catch(e){} }
      });
    } catch(e){}
  }
  try {
    var ReqB = Java.use('okhttp3.Request$Builder');
    ReqB.build.implementation = function () {
      var req = this.build();
      try {
        var url = ''+req.url().toString();
        if (hot(url)) {
          var hdrs = ''+req.headers().toString();
          var method = ''+req.method();
          var bodyHex = null, bodyLen = -1, ctype = null;
          var body = req.body();
          if (body != null) {
            try { var mt = body.contentType(); if (mt) ctype = ''+mt.toString(); } catch(e){}
            if (Buf != null) {
              try {
                var b = Buf.$new(); body.writeTo(b);
                var arr = b.readByteArray(); bodyLen = arr.length;
                var hexs=''; for (var i=0;i<arr.length && i<4096;i++){ var v=(arr[i]&0xff).toString(16); hexs+=(v.length<2?'0':'')+v; }
                bodyHex = hexs;
              } catch(e){ send({tag:'ERR', where:'body-read', err:''+e}); }
            }
          }
          send({tag:'HTTP', method:method, url:url, headers:hdrs, ctype:ctype, bodyLen:bodyLen, bodyHex:bodyHex});
        }
      } catch(e){ send({tag:'ERR', where:'okhttp-build', err:''+e}); }
      return req;
    };
    send({tag:'INFO', msg:'okhttp3 Request$Builder.build hooked (okio='+(Buf!=null)+')'});
  } catch(e){ send({tag:'WARN', where:'okhttp', err:''+e}); }

  // ---- wire headers (incl. t2 auth) via BOSS's ApiDecodeInterceptor (okhttp3 is shaded) ----
  try {
    var AI = Java.use('net.bosszhipin.base.a');
    AI.intercept.implementation = function (chain) {
      try {
        var req = chain.request();
        var u = '' + req.k().toString();
        if (hot(u)) send({tag:'HDR', url:u, headers:'' + req.e().toString()});
      } catch(e){ send({tag:'ERR', where:'hdr', err:''+e}); }
      return this.intercept(chain);
    };
    send({tag:'INFO', msg:'net.bosszhipin.base.a header-dump hooked (t2)'});
  } catch(e){ send({tag:'WARN', where:'hdr-hook', err:''+e}); }
});
