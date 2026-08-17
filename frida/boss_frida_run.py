#!/usr/bin/env python3
# Headless frida driver: attach BOSS via remote art-runtime-srv, load hook, print captures.
import sys, json, time
import frida

HOST = '127.0.0.1:27142'
# Morphida anti-detect masks process names -> attach by PID (argv[1])
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 'com.hpbr.bosszhipin'
SCRIPT = sys.argv[2] if len(sys.argv) > 2 else r'C:\Users\Administrator\AppData\Local\Temp\claude\C--work-git-code-hook-lab\dfa3dc3d-c8fe-4435-a9c1-35e66554bd5d\scratchpad\boss_search_hook.c.js'

def on_message(message, data):
    if message['type'] == 'send':
        p = message['payload']
        print('\n[CAP] ' + json.dumps(p, ensure_ascii=False, indent=2), flush=True)
    elif message['type'] == 'error':
        print('\n[ERR] ' + (message.get('stack') or str(message)), flush=True)
    else:
        print('\n[MSG] ' + str(message), flush=True)

def main():
    dev = frida.get_device_manager().add_remote_device(HOST)
    session = dev.attach(TARGET)
    print('[*] attached to %s @ %s' % (TARGET, HOST), flush=True)
    with open(SCRIPT, 'r', encoding='utf-8') as f:
        src = f.read()
    script = session.create_script(src)
    script.on('message', on_message)
    script.load()
    print('[*] script loaded, capturing (Ctrl-C to stop)...', flush=True)
    # keep alive
    while True:
        time.sleep(1)

if __name__ == '__main__':
    main()
