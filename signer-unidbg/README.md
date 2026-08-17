# signer-unidbg — verification oracle

Loads the real `libyzwg.so` in [unidbg](https://github.com/zhkl0228/unidbg) and byte-compares
its output against frida captures. This is how the pure-Python `bosscli/yzwg.py` was reversed and
is kept honest; it is **not** needed at runtime.

## Setup

Drop two files into `signer-unidbg/yzwg/` (both gitignored):

- `libyzwg-arm64-v8a.so` — from `lib/arm64-v8a/` of the BOSS直聘 APK.
- `cert.der` — the app's signing certificate in DER. JNI_OnLoad checks
  `getPackagesForUid` + `signatures[0].toCharsString().hashCode()`; feeding the **real** cert (and
  a real `String.hashCode`) is what lets `JNI_OnLoad` succeed. Extract with:
  ```bash
  keytool -printcert -rfc -jarfile app.apk > cert.pem
  # then base64-decode the CERTIFICATE block into cert.der
  ```

## Run

```bash
# JDK 21 (JBR). Verifies sig/sp against ../tests/oracle/*
./gradlew run -Dorg.gradle.java.home="C:/Program Files/Android/Android Studio/jbr"
#  -> [VERDICT] signature MATCH = true

# other modes:
./gradlew run -Dop=salt      # dump the anti-tamper SALT (qword_444470)
./gradlew run -Dop=probe     # differential structure probe (key-sensitivity, sp shape)
./gradlew run -Dop=verify2   # nativeCalculateCRC32 + nativeEncodeRequestBody oracle
```

`YzwgRunner.java` implements the JNI upcalls that satisfy the anti-tamper check (real cert DER +
`String.hashCode`) — see [[unidbg跑通libyzwg-喂真实证书过包名与签名hashCode反篡改]] in the vault.
