#!/usr/bin/env python3
"""Host-side driver for LeaseMem-Mobile experiments (Android emulators and one test phone, adb only).

Deterministic scripted "agent": no LLM. All randomness is seeded and logged.
"""
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import time
import zlib

P06 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SA = os.environ.get("SA", os.path.join(os.path.dirname(P06), "shared-android"))


def _find_adb():
    """$ADB, else <ANDROID_HOME|ANDROID_SDK_ROOT>/platform-tools/adb[.exe], else adb on PATH, else the macOS layout."""
    if os.environ.get("ADB"):
        return os.environ["ADB"]
    for home in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"), os.path.join(SA, "sdk")):
        for name in ("adb.exe", "adb"):
            if home and os.path.isfile(os.path.join(home, "platform-tools", name)):
                return os.path.join(home, "platform-tools", name)
    return shutil.which("adb") or SA + "/sdk/platform-tools/adb"


ADB = _find_adb()
CPKG = "org.leasemem.client"
TPKG = "org.leasemem.trig"
MPKG = "org.leasemem.mut"
FILES = "/data/data/%s/files" % CPKG
# P06's emulators, plus test phones named in $P06_SERIALS (comma separated). An entry matches the adb serial or the
# device's ro.serialno, so one entry covers a phone over USB and over wireless debugging (whose adb serial changes).
ALLOWED = {"emulator-5620", "emulator-5622"} | {x.strip() for x in os.environ.get("P06_SERIALS", "").split(",") if x.strip()}


def host_load():
    """Host load average. Windows has no os.getloadavg; psutil emulates it there (first call returns zeros)."""
    try:
        return os.getloadavg()
    except (AttributeError, OSError):
        try:
            import psutil
            return psutil.getloadavg()
        except ImportError:
            return None


host_load()   # prime psutil's sampler so later calls carry real values


def keep_host_awake():
    """Replaces macOS `caffeinate`: keeps a Windows host from sleeping while this process runs (no system setting changes)."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED


def open_new(path):
    """Raw data is append-only across runs: create a new file, never overwrite or append to an existing one."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return open(path, "x", encoding="utf-8")


class Dev:
    def __init__(self, serial):
        if not os.path.isfile(ADB) and not shutil.which(ADB):
            raise RuntimeError("adb not found (%s); set ANDROID_HOME or ADB" % ADB)
        try:
            state = subprocess.run([ADB, "-s", serial, "get-state"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        except subprocess.TimeoutExpired:
            raise RuntimeError("adb get-state timed out for %s" % serial)
        if state.stdout.strip() != "device":
            raise RuntimeError("device %s not attached or not authorized (adb get-state: %s); check `adb devices -l`"
                               % (serial, (state.stdout + state.stderr).strip()))
        self.s = serial
        self.seq = 0
        self._root = None
        self.frozen_method = None
        hw = self.sh("getprop ro.serialno", timeout=15).strip()
        if serial not in ALLOWED and hw not in ALLOWED:
            raise RuntimeError("%s (ro.serialno %s) is not in the allowlist; add it to P06_SERIALS only if it is the "
                               "test phone" % (serial, hw))
        keep_host_awake()

    # ---------- adb ----------
    def sh(self, cmd, timeout=60, check=False, retries=2):
        for attempt in range(retries + 1):          # adb occasionally hangs under host load: retry, then give up
            try:
                r = subprocess.run([ADB, "-s", self.s, "shell", cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
                break
            except subprocess.TimeoutExpired:
                if attempt == retries:
                    raise
                time.sleep(5)
        if check and r.returncode != 0:
            raise RuntimeError("adb shell failed: %s\n%s" % (cmd, r.stderr))
        return r.stdout.replace("\r", "")

    def adb(self, *args, timeout=120):
        if args and args[0] in ("root", "unroot", "reboot"):
            self._root = None
        return subprocess.run([ADB, "-s", self.s] + list(args), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout).stdout

    @property
    def rooted(self):
        """adbd runs as root (emulator userdebug after `adb root`). A production phone is not: app files are then
        read through `run-as` (all P06 apps are debuggable)."""
        if self._root is None:
            self._root = self.sh("id -u", timeout=15).strip() == "0"
        return self._root

    def app_sh(self, pkg, cmd, timeout=60):
        """Run cmd in pkg's data directory (/data/data/<pkg>), as root or as the app's uid."""
        if self.rooted:
            return self.sh("cd /data/data/%s && %s" % (pkg, cmd), timeout=timeout)
        return self.sh("run-as %s sh -c '%s'" % (pkg, cmd.replace("'", "'\\''")), timeout=timeout)

    def cat(self, pkg, rel):
        return self.app_sh(pkg, "cat %s 2>/dev/null" % rel)

    def rm(self, pkg, rel):
        return self.app_sh(pkg, "rm -f %s" % rel)

    def kill9(self, pkg):
        """SIGKILL the app process. The shell uid cannot signal an app uid on a production build; run-as can."""
        p = self.pid(pkg)
        if p:
            if self.rooted:
                self.sh("kill -9 %s" % p)
            else:
                self.app_sh(pkg, "kill -9 %s" % p)
        return p

    def frozen(self, pkg=CPKG):
        """'1'/'0' cached-app-freezer state, 'dead' if no process, '?' if unreadable. Reads the cgroup v2 freeze file
        (root, or a shell uid that may read /proc); otherwise falls back to ActivityManager's isFrozen flag.
        self.frozen_method records which source answered."""
        pid = self.pid(pkg)
        if not pid:
            self.frozen_method = None
            return "dead"
        path = None
        for line in self.sh("cat /proc/%s/cgroup 2>/dev/null" % pid).splitlines():
            if line.startswith("0::"):
                path = line[3:].strip()
        if path:
            v = self.sh("cat /sys/fs/cgroup%s/cgroup.freeze 2>/dev/null" % path).strip()
            if v in ("0", "1"):
                self.frozen_method = "cgroup"
                return v
        txt = self.sh("dumpsys activity processes %s" % pkg)
        at = txt.find("%s:%s/" % (pid, pkg))          # this process's ProcessRecord, not the :reference one
        m = re.search(r"isFrozen=(true|false)", txt[at:]) if at >= 0 else None
        self.frozen_method = "dumpsys" if m else None
        return ("1" if m.group(1) == "true" else "0") if m else "?"

    def plugged(self):
        """True if dumpsys battery reports any charger (AC, USB, Wireless or Dock powered)."""
        return bool(re.search(r"(AC|USB|Wireless|Dock) powered: true", self.sh("dumpsys battery")))

    def meta(self):
        """Fields every physical-phone record carries (PHYS-PROTOCOL.md)."""
        if not hasattr(self, "_meta"):
            g = lambda k: self.sh("getprop " + k, timeout=15).strip()
            self._meta = {"device": "%s %s" % (g("ro.product.manufacturer"), g("ro.product.model")),
                          "fingerprint": g("ro.build.fingerprint"), "sdk": g("ro.build.version.sdk")}
        return dict(self._meta, serial=self.s, rooted=self.rooted, plugged=self.plugged())

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
        self.rm(pkg, "files/res_%s.json" % rid)
        self.sh("am broadcast -n %s/.Cmd --es cmd %s --es id %s %s" % (pkg, cmd, rid, extra))
        t0 = time.time()
        while time.time() - t0 < timeout:
            out = self.cat(pkg, "files/res_%s.json" % rid)
            if out.startswith("{"):
                self.rm(pkg, "files/res_%s.json" % rid)
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
            out = self.cat(MPKG, "files/done_%s" % rid)
            if out.startswith("R:"):
                self.rm(MPKG, "files/done_%s" % rid)
                return json.loads(out[2:])
            time.sleep(0.1)
        raise TimeoutError("mut " + op)

    def home(self):
        self.sh("input keyevent KEYCODE_HOME")

    def trig_log(self):
        return self.cat(TPKG, "files/trig.log")

    def trig_log_clear(self):
        self.app_sh(TPKG, ": > files/trig.log")

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
