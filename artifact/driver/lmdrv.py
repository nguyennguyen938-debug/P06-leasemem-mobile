#!/usr/bin/env python3
"""Host-side driver for LeaseMem-Mobile experiments (real Android 13 emulator, adb only).

Deterministic scripted "agent": no LLM. All randomness is seeded and logged.
"""
import json
import os
import random
import struct
import subprocess
import time
import zlib

P06 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SA = os.environ.get("SA", os.path.join(os.path.dirname(P06), "shared-android"))
ADB = SA + "/sdk/platform-tools/adb"
CPKG = "org.leasemem.client"
TPKG = "org.leasemem.trig"
FILES = "/data/data/%s/files" % CPKG
ALLOWED = {"emulator-5620", "emulator-5622"}   # P06's instances only


class Dev:
    def __init__(self, serial):
        assert serial in ALLOWED, serial
        self.s = serial
        self.seq = 0

    # ---------- adb ----------
    def sh(self, cmd, timeout=60, check=False, retries=2):
        for attempt in range(retries + 1):          # adb occasionally hangs under host load: retry, then give up
            try:
                r = subprocess.run([ADB, "-s", self.s, "shell", cmd], capture_output=True, text=True, timeout=timeout)
                break
            except subprocess.TimeoutExpired:
                if attempt == retries:
                    raise
                time.sleep(5)
        if check and r.returncode != 0:
            raise RuntimeError("adb shell failed: %s\n%s" % (cmd, r.stderr))
        return r.stdout.replace("\r", "")

    def adb(self, *args, timeout=120):
        return subprocess.run([ADB, "-s", self.s] + list(args), capture_output=True, text=True, timeout=timeout).stdout

    def now_ms(self):
        return int(self.sh("date +%s%3N").strip())

    def wait_boot(self, timeout=300):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if self.sh("getprop sys.boot_completed", timeout=10).strip() == "1":
                    return time.time() - t0
            except Exception:
                pass
            time.sleep(2)
        raise RuntimeError("boot timeout")

    def pid(self, pkg=CPKG):
        return self.sh("pidof %s" % pkg).strip()

    # ---------- client commands ----------
    def cmd(self, cmd, extra="", timeout=40, pkg=CPKG):
        self.seq += 1
        rid = "%d_%d" % (int(time.time() * 1000) % 10**9, self.seq)
        self.sh("rm -f %s/res_%s.json" % (FILES, rid))
        self.sh("am broadcast -n %s/.Cmd --es cmd %s --es id %s %s" % (pkg, cmd, rid, extra))
        t0 = time.time()
        while time.time() - t0 < timeout:
            out = self.sh("cat %s/res_%s.json 2>/dev/null" % (FILES, rid))
            if out.startswith("{"):
                self.sh("rm -f %s/res_%s.json" % (FILES, rid))
                return json.loads(out)
            time.sleep(0.15)
        raise TimeoutError("no response to %s %s" % (cmd, rid))

    def launch(self, pkg=CPKG):
        self.sh("am start -W -n %s/.Main" % pkg, timeout=60)
        for _ in range(60):
            if self.pid(pkg):
                return True
            time.sleep(0.2)
        return False

    def mut(self, op, a="", b="", extra="", timeout=20):
        """Mutate shared media/files as another app (org.leasemem.mut) through MediaStore / FUSE file I/O."""
        self.seq += 1
        rid = "m%d" % self.seq
        self.sh("am broadcast -f 32 -n org.leasemem.mut/.Cmd --es op %s --es a '%s' --es b '%s' --es id %s %s" % (op, a, b, rid, extra))
        t0 = time.time()
        while time.time() - t0 < timeout:
            out = self.sh("cat /data/data/org.leasemem.mut/files/done_%s 2>/dev/null" % rid)
            if out.startswith("R:"):
                self.sh("rm -f /data/data/org.leasemem.mut/files/done_%s" % rid)
                return json.loads(out[2:])
            time.sleep(0.1)
        raise TimeoutError("mut " + op)

    def home(self):
        self.sh("input keyevent KEYCODE_HOME")

    def trig_log(self):
        return self.sh("cat /data/data/%s/files/trig.log 2>/dev/null" % TPKG)

    def trig_cmd(self, cmd):
        self.sh("am broadcast -n %s/.Cmd --es cmd %s" % (TPKG, cmd))


# ---------- tiny PNG for media mutations ----------
def png_bytes(seed):
    w = h = 8
    rnd = random.Random(seed)
    raw = b"".join(b"\x00" + bytes(rnd.randrange(256) for _ in range(w * 3)) for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


# ---------- sources: setup + mutations (all via public provider APIs or the FUSE file path) ----------
PHONE = "vnd.android.cursor.item/phone_v2"
DOC = "/storage/emulated/0/Documents/lm"
NAME = "vnd.android.cursor.item/name"


class World:
    """Ground-truth-tracking mutator. Mutations are performed by a separate app (org.leasemem.mut) through public
    Android APIs; every mutation records what it did and the device time before/after."""

    KINDS = {"contacts": ["update", "delete", "insert"], "sms": ["insert", "update", "delete"],
             "calllog": ["insert", "update", "delete"], "media": ["insert", "update", "delete"],
             "calendar": ["update", "delete", "insert"], "settings": ["update"],
             "files": ["update", "insert", "delete"]}

    def __init__(self, dev, rng):
        self.d = dev
        self.r = rng
        self.n = 0

    def ensure_base(self):
        r = self.d.mut("ensure")
        if not r.get("ok"):
            raise RuntimeError("ensure failed: %s" % r)
        return r

    def mutate(self, src, kind):
        self.n += 1
        tag = "%d%03d" % (int(time.time()) % 100000, self.n % 1000)
        r = self.d.mut("mutate", src, kind, extra="--es tag %s" % tag)
        if not r.get("ok"):
            raise RuntimeError("mutate failed: %s %s %s" % (src, kind, r))
        return {"src": src, "kind": kind, "tag": tag, "t_pre": r["t_pre"], "t_dev": r["t_post"], "did": r.get("did")}
