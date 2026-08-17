package lab.boss;

import com.github.unidbg.AndroidEmulator;
import com.github.unidbg.Module;
import com.github.unidbg.linux.android.AndroidEmulatorBuilder;
import com.github.unidbg.linux.android.AndroidResolver;
import com.github.unidbg.linux.android.dvm.AbstractJni;
import com.github.unidbg.linux.android.dvm.BaseVM;
import com.github.unidbg.linux.android.dvm.DalvikModule;
import com.github.unidbg.linux.android.dvm.DvmClass;
import com.github.unidbg.linux.android.dvm.DvmObject;
import com.github.unidbg.linux.android.dvm.StringObject;
import com.github.unidbg.linux.android.dvm.VM;
import com.github.unidbg.linux.android.dvm.VarArg;
import com.github.unidbg.linux.android.dvm.VaList;
import com.github.unidbg.linux.android.dvm.array.ByteArray;
import com.github.unidbg.linux.android.dvm.array.ArrayObject;
import com.github.unidbg.memory.Memory;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

/**
 * unidbg driver for BOSS直聘 libyzwg.so (com.twl.signer.YZWG).
 * Reproduces the request signer off-device:
 *   nativeSignature([B, String) -> byte[]   ==> sig "V3.<hex>"  (a.i)
 *   nativeEncodeRequest([B, String) -> String ==> sp             (a.d)
 * Verifies against a frida-captured (input,key,sig) oracle.
 */
public class YzwgRunner extends AbstractJni {

    // Drop libyzwg-arm64-v8a.so (from lib/arm64-v8a/ of the BOSS APK) and the app cert DER
    // into signer-unidbg/yzwg/ , or override with -Dso=... -Dcert=... . Both are gitignored.
    static final String SO   = System.getProperty("so",   "yzwg/libyzwg-arm64-v8a.so");
    static final String CLS  = "com/twl/signer/YZWG";
    static final String PKG  = "com.hpbr.bosszhipin";
    static final String CERT = System.getProperty("cert", "yzwg/cert.der");
    static byte[] CERT_DER;
    static {
        try { CERT_DER = Files.readAllBytes(Paths.get(CERT)); }
        catch (Exception e) { CERT_DER = new byte[0]; }
    }

    private final AndroidEmulator emulator;
    private final VM vm;
    private final DvmClass cYzwg;
    private final Module module;

    public YzwgRunner() {
        emulator = AndroidEmulatorBuilder.for64Bit().setProcessName(PKG).build();
        Memory memory = emulator.getMemory();
        memory.setLibraryResolver(new AndroidResolver(23));
        vm = emulator.createDalvikVM();
        vm.setJni(this);
        vm.setVerbose("1".equals(System.getProperty("vmverbose")));
        DalvikModule dm = vm.loadLibrary(new File(SO), true);
        dm.callJNI_OnLoad(emulator);
        module = dm.getModule();
        cYzwg = vm.resolveClass(CLS);
        System.out.println("[+] libyzwg loaded @0x" + Long.toHexString(module.base) + ", JNI_OnLoad done");
    }

    String nativeSignature(byte[] data, String key) {
        DvmObject<?> r = cYzwg.callStaticJniMethodObject(emulator,
                "nativeSignature([BLjava/lang/String;)[B",
                new ByteArray(vm, data), key == null ? null : new StringObject(vm, key));
        if (r == null) return null;
        Object v = r.getValue();
        return (v instanceof byte[]) ? new String((byte[]) v, StandardCharsets.UTF_8) : String.valueOf(v);
    }

    String nativeEncodeRequest(byte[] data, String key) {
        DvmObject<?> r = cYzwg.callStaticJniMethodObject(emulator,
                "nativeEncodeRequest([BLjava/lang/String;)Ljava/lang/String;",
                new ByteArray(vm, data), key == null ? null : new StringObject(vm, key));
        return r == null ? null : String.valueOf(r.getValue());
    }

    public static void main(String[] args) throws Exception {
        YzwgRunner r = new YzwgRunner();

        String op = System.getProperty("op", "");
        if ("salt".equals(op)) {
            long p = r.module.base + 0x444470L;
            byte[] pb = r.emulator.getBackend().mem_read(p, 8);
            long saltPtr = java.nio.ByteBuffer.wrap(pb).order(java.nio.ByteOrder.LITTLE_ENDIAN).getLong();
            byte[] sb = r.emulator.getBackend().mem_read(saltPtr, 48);
            int z = 0; while (z < sb.length && sb[z] != 0) z++;
            String salt = new String(sb, 0, z, StandardCharsets.UTF_8);
            System.out.println("[salt] qword_444470 -> " + Long.toHexString(saltPtr) + "  salt=\"" + salt + "\" len=" + z);
            return;
        }
        if ("verify2".equals(op)) {
            java.nio.charset.Charset U = StandardCharsets.UTF_8;
            String K = "82a8b7f0c9b504426ae7abe305d1e388";
            for (String s : new String[]{"", "A", "hello world", "ABCDEFGHIJKLMNOP"}) {
                DvmObject<?> crc = r.cYzwg.callStaticJniMethodObject(r.emulator,
                    "nativeCalculateCRC32([B)Ljava/lang/String;", new ByteArray(r.vm, s.getBytes(U)));
                DvmObject<?> body = r.cYzwg.callStaticJniMethodObject(r.emulator,
                    "nativeEncodeRequestBody([BLjava/lang/String;)[B",
                    new ByteArray(r.vm, s.getBytes(U)), new StringObject(r.vm, K));
                Object bv = body == null ? null : body.getValue();
                String bhex = (bv instanceof byte[]) ? toHex((byte[]) bv) : "null";
                System.out.println("[v2] in=\"" + s + "\" crc32=" + (crc==null?"null":crc.getValue())
                        + " bodyhex=" + bhex);
            }
            return;
        }
        if ("probe".equals(op)) { probe(r); return; }
        if ("sign".equals(op)) {
            // ad-hoc: -Dop=sign -DinHex=<hex of signedInput> -Dkey=<key|null>
            byte[] in = hex(System.getProperty("inHex", ""));
            String key = System.getProperty("key", "null");
            if ("null".equals(key) || key.isEmpty()) key = null;
            System.out.println("[sign] sig= " + r.nativeSignature(in, key));
            System.out.println("[sign] sp = " + r.nativeEncodeRequest(in, key));
            return;
        }

        // default: verify against captured oracle
        byte[] input = Files.readAllBytes(Paths.get(System.getProperty("oracle","../tests/oracle"), "oracle_input.bin"));
        String key = new String(Files.readAllBytes(Paths.get(System.getProperty("oracle","../tests/oracle"), "oracle_key.txt")), StandardCharsets.UTF_8).trim();
        String expSig = new String(Files.readAllBytes(Paths.get(System.getProperty("oracle","../tests/oracle"), "oracle_sig.txt")), StandardCharsets.UTF_8).trim();
        if ("null".equals(key) || key.isEmpty()) key = null;

        System.out.println("[oracle] inlen=" + input.length + " key=" + key + " expSig=" + expSig);
        String sig = r.nativeSignature(input, key);
        System.out.println("[result] nativeSignature => " + sig);
        System.out.println("[result] expected        => " + expSig);
        System.out.println("[VERDICT] signature MATCH = " + expSig.equals(sig));

        // verify encodeRequest (sp) against a captured (strD,key,sp-prefix) oracle
        try {
            byte[] spIn = Files.readAllBytes(Paths.get(System.getProperty("oracle","../tests/oracle"), "oracle_sp_input.bin"));
            String spKey = new String(Files.readAllBytes(Paths.get(System.getProperty("oracle","../tests/oracle"), "oracle_sp_key.txt")), StandardCharsets.UTF_8).trim();
            String spPrefix = new String(Files.readAllBytes(Paths.get(System.getProperty("oracle","../tests/oracle"), "oracle_sp_prefix.txt")), StandardCharsets.UTF_8).trim();
            if ("null".equals(spKey) || spKey.isEmpty()) spKey = null;
            String sp = r.nativeEncodeRequest(spIn, spKey);
            boolean ok = sp != null && sp.startsWith(spPrefix);
            System.out.println("[result] nativeEncodeRequest(sp) prefix(" + spPrefix.length() + ") MATCH = " + ok);
            System.out.println("           got head = " + (sp == null ? "null" : sp.substring(0, Math.min(spPrefix.length(), sp.length()))));
            // determinism: same input twice -> identical output?
            System.out.println("[result] sp deterministic = " + java.util.Objects.equals(sp, r.nativeEncodeRequest(spIn, spKey)));
        } catch (java.nio.file.NoSuchFileException nf) {
            System.out.println("[result] no sp oracle, skipping sp check");
        } catch (Throwable t) {
            System.out.println("[result] sp check threw: " + t);
        }
    }

    // Differential probe: reveal structure of nativeSignature/nativeEncodeRequest without reading asm.
    static void probe(YzwgRunner r) throws Exception {
        java.nio.charset.Charset U = StandardCharsets.UTF_8;
        String K = "82a8b7f0c9b504426ae7abe305d1e388";
        String K2= "00000000000000000000000000000000";
        p("== SIGNATURE key-sensitivity & avalanche ==");
        byte[] base = "client_info=x&req_time=1&v=14.050".getBytes(U);
        p("sig(base, K)   = " + r.nativeSignature(base, K));
        p("sig(base, null)= " + r.nativeSignature(base, null));
        p("sig(base, K2)  = " + r.nativeSignature(base, K2));
        p("sig(base, K)#2 = " + r.nativeSignature(base, K) + "   (determinism)");
        byte[] flip = base.clone(); flip[0] ^= 1;
        p("sig(flip1bit,K)= " + r.nativeSignature(flip, K));
        p("-- small inputs (find fixed salt / structure), key=K --");
        for (String s : new String[]{"", "a", "ab", "abc", "abcd", "0000000000000000"})
            p(String.format("  sig(%-18s len=%2d) = %s", '"'+s+'"', s.length(), r.nativeSignature(s.getBytes(U), K)));
        p("-- same inputs, key=null --");
        for (String s : new String[]{"", "a", "abc"})
            p(String.format("  sig(%-6s null) = %s", '"'+s+'"', r.nativeSignature(s.getBytes(U), null)));

        p("\n== ENCODE-REQUEST (sp) shape ==");
        for (int n : new int[]{0,1,15,16,17,31,32,33,64}) {
            byte[] b = new byte[n]; for (int i=0;i<n;i++) b[i]=(byte)('A'+(i%26));
            String sp = r.nativeEncodeRequest(b, K);
            p(String.format("  sp(inlen=%2d, K)  outlen=%3d  head=%s", n, sp==null?-1:sp.length(),
                    sp==null?"null":sp.substring(0, Math.min(48, sp.length()))));
        }
        p("-- sp key-sensitivity (inlen=16) --");
        byte[] b16 = "ABCDEFGHIJKLMNOP".getBytes(U);
        p("  sp(b16, K)    = " + r.nativeEncodeRequest(b16, K));
        p("  sp(b16, null) = " + r.nativeEncodeRequest(b16, null));
        p("  sp(b16, K2)   = " + r.nativeEncodeRequest(b16, K2));
        p("  sp(b16, K)#2  = " + r.nativeEncodeRequest(b16, K) + "   (determinism)");
        p("-- sp incremental byte (ECB block-independence test) --");
        p("  sp(16*'A')    = " + r.nativeEncodeRequest("AAAAAAAAAAAAAAAA".getBytes(U), K));
        p("  sp(32*'A')    = " + r.nativeEncodeRequest("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA".getBytes(U), K));
        p("  sp(16A+16B)   = " + r.nativeEncodeRequest("AAAAAAAAAAAAAAAABBBBBBBBBBBBBBBB".getBytes(U), K));
    }
    static void p(String s){ System.out.println("[probe] " + s); }

    static byte[] hex(String s) {
        int n = s.length() / 2;
        byte[] b = new byte[n];
        for (int i = 0; i < n; i++) b[i] = (byte) Integer.parseInt(s.substring(2 * i, 2 * i + 2), 16);
        return b;
    }

    // ---- JNI upcalls ----
    // JNI_OnLoad does an anti-repackaging check: gContext.getPackageManager().getPackagesForUid(uid)
    // must contain the real package name. Feed it Context/PackageManager/String[] with our pkg.
    @Override
    public DvmObject<?> callObjectMethod(BaseVM b, DvmObject<?> obj, String sig, VarArg va) {
        if (sig.contains("->getPackageManager("))
            return vm.resolveClass("android/content/pm/PackageManager").newObject(null);
        if (sig.contains("->getApplicationContext(") || sig.contains("->getBaseContext("))
            return obj;
        if (sig.contains("->getPackagesForUid("))
            return new ArrayObject(new StringObject(vm, PKG));
        if (sig.contains("->getPackageName("))
            return new StringObject(vm, PKG);
        if (sig.contains("->getPackageInfo("))
            return vm.resolveClass("android/content/pm/PackageInfo").newObject(null);
        if (sig.contains("android/content/pm/Signature->toByteArray("))
            return new ByteArray(vm, CERT_DER);
        if (sig.contains("android/content/pm/Signature->toCharsString(")
            || sig.contains("android/content/pm/Signature->toString("))
            return new StringObject(vm, toHex(CERT_DER));
        System.out.println("[upcall-obj] " + sig);
        return new StringObject(vm, "");
    }

    @Override
    public DvmObject<?> getObjectField(BaseVM b, DvmObject<?> obj, String sig) {
        if (sig.contains("PackageInfo->signatures"))   // Signature[] with the real cert
            return new ArrayObject(vm.resolveClass("android/content/pm/Signature").newObject(CERT_DER));
        System.out.println("[ofield] " + sig);
        return vm.resolveClass("java/lang/Object").newObject(null);
    }

    static String toHex(byte[] b) {
        StringBuilder s = new StringBuilder();
        for (byte x : b) s.append(String.format("%02x", x & 0xff));
        return s.toString();
    }
    @Override
    public DvmObject<?> callStaticObjectMethod(BaseVM b, DvmClass c, String sig, VarArg va) {
        System.out.println("[upcall-sobj] " + sig);
        return new StringObject(vm, "");
    }
    @Override
    public DvmObject<?> getStaticObjectField(BaseVM b, DvmClass c, String sig) {
        if (sig.startsWith("com/twl/signer/YZWG->gContext"))
            return vm.resolveClass("android/content/Context").newObject(null);
        System.out.println("[sfield-obj] " + sig);
        return new StringObject(vm, "");
    }
    @Override
    public int getStaticIntField(BaseVM b, DvmClass c, String sig) {
        System.out.println("[sfield-int] " + sig);
        return 0;
    }

    // native compares signatures[0].toCharsString().hashCode() to an embedded constant.
    @Override
    public int callIntMethod(BaseVM b, DvmObject<?> obj, String sig, VarArg va) { return intM(obj, sig); }
    @Override
    public int callIntMethodV(BaseVM b, DvmObject<?> obj, String sig, VaList va) { return intM(obj, sig); }
    private int intM(DvmObject<?> obj, String sig) {
        if (sig.contains("String->hashCode(")) return String.valueOf(obj.getValue()).hashCode();
        System.out.println("[upcall-int] " + sig);
        return 0;
    }
}
