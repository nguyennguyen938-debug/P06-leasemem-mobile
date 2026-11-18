#!/usr/bin/env python3
"""Host-side driver for LeaseMem-Mobile experiments (Android emulators and rented phones, adb only).

Deterministic scripted "agent": no LLM. All randomness is seeded and logged.

Device classes (PHYS-PROTOCOL.md):
- P06's two emulators (emulator-5620, emulator-5622): the historical runs, unchanged.
- AWS mode (P06_TARGET=aws, or DEVICEFARM_DEVICE_UDID set by the Device Farm test host): a freshly wiped rented
  phone. Experiments run in user 0 with every source (SMS and call log included); the guard below still applies,
  except that clock changes are allowed so B0 can probe them. The device is the one Device Farm names in
  DEVICEFARM_DEVICE_UDID; records carry device_instance, device_arn and run_arn.
- The user's personal Galaxy A35 (serial RFCXA0TTMPP) is blocked in every mode: Dev refuses it before any adb call
  and refuses any device whose ro.serialno is that serial.
- Any other allowlisted phone (P06_SERIALS) uses the personal-phone isolation of E5, described next. It is kept
  for completeness; no personal phone is used (the user's phone cannot create a second user).

On a non-emulator device that is not in AWS mode, Dev enforces:
- every experiment runs in the Android user named "P06 Test" (never user 0); Dev refuses to start otherwise, refuses
  a phone whose adbd runs as root, and refuses unless that user is in the foreground;
- every user-scoped command (am, pm, appops, content, cmd role, run-as, install) is built by Dev.u() or
  Dev.install(), which add --user <that id>; Dev.sh() refuses any command that lacks it or names another user,
  any banned command (pm clear, user management, clock changes, root, setprop, batterystats reset, shared storage,
  settings other than P06's own lm_* keys), and any dumpsys outside a short allowlist;
- SMS is never touched (its provider is shared by all Android users), and the call log is used only if the test
  user carries the no_outgoing_calls restriction (calls off, so its call history is its own);
- drivers run only under physical/campaign.py, which records device-wide settings first and restores them after
  every step, also when a step fails; a reboot needs the campaign's --allow-reboot, and after it the driver only
  waits for the user to switch back to P06 Test.
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
ADB_CMD = [sys.executable, ADB] if ADB.endswith(".py") else [ADB]   # a .py path is the E7 fake adb
CPKG = "org.leasemem.client"
TPKG = "org.leasemem.trig"
MPKG = "org.leasemem.mut"
APKG = "org.leasemem.assist"
FILES = "/data/data/%s/files" % CPKG
EMULATORS = {"emulator-5620", "emulator-5622"}
TEST_USER = "P06 Test"
# P06's emulators, plus test phones named in $P06_SERIALS (comma separated). An entry matches the adb serial or the
# device's ro.serialno, so one entry covers a phone over USB and over wireless debugging (whose adb serial changes).
# The user's personal phone: never used for any experiment, in any mode (it cannot create a second user).
BLOCKED_SERIALS = {"RFCXA0TTMPP"}
AWS = os.environ.get("P06_TARGET") == "aws" or bool(os.environ.get("DEVICEFARM_DEVICE_UDID"))
ALLOWED = (EMULATORS | {x.strip() for x in os.environ.get("P06_SERIALS", "").split(",") if x.strip()}
           | ({os.environ["DEVICEFARM_DEVICE_UDID"]} if os.environ.get("DEVICEFARM_DEVICE_UDID") else set()))


def blocked(serial):
    """True for the user's personal phone, also inside a longer adb serial (mDNS or wireless names)."""
    return any(b in (serial or "") for b in BLOCKED_SERIALS)
PERMS = ["READ_CONTACTS", "WRITE_CONTACTS", "READ_CALL_LOG", "WRITE_CALL_LOG", "READ_CALENDAR", "WRITE_CALENDAR",
         "READ_MEDIA_IMAGES", "READ_EXTERNAL_STORAGE", "POST_NOTIFICATIONS", "READ_SMS", "WRITE_SECURE_SETTINGS"]
PERM_SOURCE = {"READ_SMS": "sms", "READ_CALL_LOG": "calllog", "WRITE_CALL_LOG": "calllog"}
# Sources P06 cannot write on Device Farm's Pixel 8 (B0 run 97a66c65): SMS, because the mutator cannot hold the SMS
# role and its inserts are dropped; the call log, because rows the mutator inserts are not returned by its own queries
# (b0_probe calllog_diag looks for the cause). Every record carries excluded_sources; the analysis reads it from there.
AWS_EXCLUDED = ("sms", "calllog")
# Package dump (runtime permission state). On Device Farm's Pixel 8 only this exact form read back: `dumpsys package
# <pkg> 2>&1` worked in the B0 probes (runs 1c18f498 and before), the plain form and `dumpsys -t 60 package <pkg> 2>&1`
# came back empty in every restore read-back (runs 1c18f498, 5ec38290).
DUMP_PKG = "dumpsys package %s 2>&1"

if os.environ.get("P06_FAKE_TIME"):     # E7 dry run against the fake adb: a virtual clock, so waits cost ~nothing
    _off, _sleep, _time, _mono = [0.0], time.sleep, time.time, time.monotonic

    def _vsleep(s):
        _off[0] += max(0.0, s); _sleep(min(max(0.0, s), 0.002))
    time.sleep, time.time, time.monotonic = _vsleep, (lambda: _time() + _off[0]), (lambda: _mono() + _off[0])

# ---------- personal-phone guard (applies to every device except the two emulators) ----------
_AT = r"(?:^|[;&|(`]|\$\(|\bdo\s|\bthen\s|-c\s+')\s*"         # a command position inside a shell string
SCOPED = re.compile(_AT + r"(am|pm|appops|content|run-as|cmd)\s([^;&|`)]*)")
USER_ADMIN = re.compile(r"(pm list users|am get-current-user|am get-started-user-state \d+)\s*")
BANNED = re.compile(r"batterystats\s+--reset|/sdcard|/storage/|/data/|" + _AT + r"("
    r"pm\s+(create-user|remove-user|disable\S*|hide|suspend|set-user-restriction|reset-permissions)\b"
    r"|pm\s+uninstall\s+(?!--user\s+\d+\s+org\.leasemem\.\w+\s*$)|am\s+(switch-user|stop-user|start-user)\b"
    r"|locksettings\b|svc\b|su\b|setprop\b|reboot\b|wipe\b|recovery\b"
    r"|content\s+(insert|update|delete)\b|settings\s+(?!(get|put|delete)\s+global\s+(lm_mode|lm_target|auto_time|cached_apps_freezer)\b)"
    r"|device_config\s+(?!((get|put|delete)\s+activity_manager_native_boot\s+freeze_debounce_timeout|(set|get)_sync_disabled_for_tests)\b))")
# pm clear: refused everywhere except one exact command in AWS mode, clearing the Contacts provider of user 0 on a
# wiped rented phone (B0 probe; the Contacts reset of revision/supplement.py). Never on a personal phone.
PM_CLEAR_AWS_OK = re.compile(r"pm clear --user 0 com\.android\.providers\.contacts\s*")
# run-as without --user: refused everywhere except this read-only probe in AWS mode (user 0 is run-as's default), run
# once by runas_diag() after an unanswered app command, to tell a failing `--user` option from a failing run-as.
RUNAS_ID_AWS_OK = re.compile(r"run-as org\.leasemem\.\w+ id( 2>)?\s*")
# Clock changes, and the cached-apps freezer switch: refused on a personal phone; allowed in AWS mode, where B0 probes
# whether the shell can set the time and campaign.py turns the freezer on where a rented unit has it off.
CLOCK = re.compile(r"\bauto_time|\bcached_apps_freezer\b|" + _AT + r"(date\s+(-s|@|\d)|cmd\s+(alarm|time)\b)")
DUMPSYS_OK = [re.compile(p + r"\s*") for p in (
    r"battery( unplug| reset)?( \| grep .*)?", r"deviceidle (get (deep|light)|force-idle( deep)?|force-inactive|unforce|step( deep)?)",
    r"activity settings( \| grep .*)?", r"activity (processes|services) org\.leasemem\S*", r"(-t \d+ )?(package|meminfo) org\.leasemem\S*( 2>)?",
    r"batterystats --charged org\.leasemem\S*", r"power \| grep -m1 mWakefulness=", r"voiceinteraction \| grep .*",
    r"user \| awk .*", r"activity oom \| grep -m3 leasemem")]


class GuardError(RuntimeError):
    pass


def phone_violation(cmd, user, aws=False):
    """Why `cmd` may not reach a non-emulator device whose experiment user is `user`, or None. aws=True: a rented
    Device Farm phone (user 0; clock changes allowed). Used by Dev.sh(), the fake adb and the tests."""
    m = BANNED.search(cmd) or (None if aws else CLOCK.search(cmd))
    if m:
        return "banned: %r" % m.group(0)
    for m in SCOPED.finditer(cmd):
        tool, seg = m.group(1), (m.group(1) + " " + m.group(2)).strip()
        if USER_ADMIN.fullmatch(seg):
            continue
        if tool == "pm" and re.match(r"pm\s+clear\b", seg) and not (aws and PM_CLEAR_AWS_OK.fullmatch(seg)):
            return "banned: %r" % seg
        if tool == "run-as" and aws and RUNAS_ID_AWS_OK.fullmatch(seg):
            continue
        if tool == "cmd" and aws and seg.startswith("cmd alarm "):
            continue                                       # AWS: B0 probes setting the clock (not user-scoped)
        if tool == "cmd" and not seg.startswith("cmd role "):
            return "cmd other than role: %r" % seg
        users = re.findall(r"--user\s+(\S+)", seg)
        if users != [str(user)]:
            return "user-scoped command without --user %s: %r" % (user, seg)
    for m in re.finditer(r"\bdumpsys\b\s*([^;&`)]*)", cmd):
        if not any(p.fullmatch(m.group(1)) for p in DUMPSYS_OK):
            return "dumpsys not in allowlist: %r" % m.group(0)
    return None


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
        if blocked(serial):
            raise GuardError("%s is the user's personal phone; P06 never uses it" % serial)
        if serial not in ALLOWED:
            raise RuntimeError("%s is not in the allowlist (P06's emulators, P06_SERIALS, or the Device Farm UDID)" % serial)
        if not os.path.isfile(ADB) and not shutil.which(ADB):
            raise RuntimeError("adb not found (%s); set ANDROID_HOME or ADB" % ADB)
        try:
            state = subprocess.run(ADB_CMD + ["-s", serial, "get-state"], capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired:
            raise RuntimeError("adb get-state timed out for %s" % serial)
        if state.stdout.strip() != "device":
            raise RuntimeError("device %s not attached or not authorized (adb get-state: %s); check `adb devices -l`"
                               % (serial, (state.stdout + state.stderr).strip()))
        self.s, self.seq, self._root, self.frozen_method = serial, 0, None, None
        self.emulator = serial in EMULATORS
        self.aws = AWS and not self.emulator
        self.user, self.excluded, self.restrictions = (0 if self.emulator or self.aws else None), set(), set()
        if blocked(self.sh("getprop ro.serialno", timeout=15).strip()):
            raise GuardError("%s reports the serial of the user's personal phone; P06 never uses it" % serial)
        if self.aws:
            if not os.environ.get("P06_CAMPAIGN"):
                raise RuntimeError("in AWS mode, run drivers through physical/campaign.py")
            if self.rooted:
                raise RuntimeError("adbd runs as root on this device; P06 runs unrooted")
            self.excluded = set(AWS_EXCLUDED)
            self.require_fg()
        elif not self.emulator:
            if not os.environ.get("P06_CAMPAIGN"):
                raise RuntimeError("on the phone, run drivers through physical/campaign.py (it records and restores "
                                   "device-wide settings)")
            if self.rooted:
                raise RuntimeError("adbd runs as root on this phone; P06 never uses root on the personal phone")
            ids = [int(i) for i, name in re.findall(r"UserInfo\{(\d+):([^:}]*):", self.sh("pm list users", timeout=15))
                   if name == TEST_USER]
            if len(ids) != 1 or ids[0] == 0:
                raise RuntimeError("need exactly one Android user named %r other than user 0 (found ids %s); create it "
                                   "in Settings, see PHYS-PROTOCOL.md section 3" % (TEST_USER, ids))
            self.user = ids[0]
            self.restrictions = self.user_restrictions()
            # SMS storage is shared by all users: never touched. The call log is the user's own only while calls are off.
            self.excluded = {"sms"} | (set() if "no_outgoing_calls" in self.restrictions else {"calllog"})
            self.require_fg()
        keep_host_awake()

    # ---------- adb ----------
    def sh(self, cmd, timeout=60, check=False, retries=2):
        if not self.emulator:
            why = phone_violation(cmd, self.user, self.aws)
            if why:
                raise GuardError("refused on %s (%s)" % ("the rented phone" if self.aws else "the personal phone", why))
        for attempt in range(retries + 1):          # adb occasionally hangs under host load: retry, then give up
            try:
                r = subprocess.run(ADB_CMD + ["-s", self.s, "shell", cmd], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=timeout)
                break
            except subprocess.TimeoutExpired:
                if attempt == retries:
                    raise
                time.sleep(5)
        if check and r.returncode != 0:
            raise RuntimeError("adb shell failed: %s\n%s" % (cmd, r.stderr))
        return r.stdout.replace("\r", "")

    def adb(self, *args, timeout=120):
        a0 = args[0] if args else ""
        if not self.emulator:
            if a0 == "root":
                return ""                                    # never ask the personal phone for root
            if a0 == "reboot":
                if os.environ.get("P06_ALLOW_REBOOT") != "1":
                    raise GuardError("reboot refused: the user has not allowed reboots for this run (--allow-reboot)")
                pause = os.environ.get("P06_FG_PAUSE_FILE")
                if pause:
                    open(pause, "w").close()                 # campaign's foreground watchdog waits for after_reboot()
            if a0 == "install" and list(args[1:3]) != ["--user", str(self.user)]:
                raise GuardError("install without --user %s refused" % self.user)
            if a0 in ("uninstall", "push", "pull", "sideload", "restore", "backup", "disable-verity", "remount", "unroot"):
                raise GuardError("adb %s refused on the personal phone" % a0)
            if a0 == "shell":
                why = phone_violation(" ".join(args[1:]), self.user, self.aws)
                if why:
                    raise GuardError("refused on the personal phone (%s)" % why)
        if a0 in ("root", "unroot", "reboot"):
            self._root = None
        r = subprocess.run(ADB_CMD + ["-s", self.s] + list(args), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        # adb install reports a failure (e.g. INSTALL_FAILED_UPDATE_INCOMPATIBLE) on stderr: the Device Farm host's adb
        # 1.0.39 did so in B0 run e035a924, and provision() never saw the reason
        return r.stdout + (r.stderr if a0 == "install" else "")

    def u(self, cmd):
        """Add --user <test user> to a user-scoped command: 'am start -n x' -> 'am start --user 10 -n x'.
        run-as takes it after the package (`run-as <pkg> --user <id> <cmd>`): Android 15's run-as read
        `run-as --user 0 <pkg>` as package "--user" (B0 run 19ba952e on a Pixel 8)."""
        if cmd.startswith("run-as "):
            p = cmd.split(" ", 2); head, rest = " ".join(p[:2]), (p[2] if len(p) > 2 else "")
        elif cmd.startswith("cmd role "):
            p = cmd.split(" ", 3); head, rest = " ".join(p[:3]), (p[3] if len(p) > 3 else "")
        elif cmd.split(" ", 1)[0] in ("am", "pm", "appops", "content"):
            k = 3 if cmd.startswith("pm list ") else 2      # `pm list packages --user 0 x`, not `pm list --user 0 packages x`
            p = cmd.split(" ", k); head, rest = " ".join(p[:k]), (p[k] if len(p) > k else "")
        else:
            raise ValueError("not a user-scoped command: " + cmd)
        return ("%s --user %d %s" % (head, self.user, rest)).rstrip()

    def install(self, apk):
        if self.emulator or self.aws:     # emulators and wiped rented phones: all runtime permissions granted
            return self.adb("install", "--user", str(self.user), "-r", "-g", apk)
        return self.adb("install", "--user", str(self.user), "-r", apk)

    @property
    def rooted(self):
        """adbd runs as root (emulator userdebug after `adb root`). A production phone is not: app files are then
        read through `run-as` (all P06 apps are debuggable)."""
        if self._root is None:
            self._root = self.sh("id -u", timeout=15).strip() == "0"
        return self._root

    # ---------- the test user ----------
    def current_user(self):
        out = self.sh("am get-current-user", timeout=15).strip()
        return int(out) if out.isdigit() else None

    def require_fg(self):
        """Stop if the test user is not the foreground user: key events and activity starts would reach another user."""
        if not self.emulator and self.current_user() != self.user:
            raise GuardError("Android user %r (id %s) is not in the foreground; switch to it on the phone"
                             % (TEST_USER, self.user))

    def user_restrictions(self):
        """User restrictions of the test user, read on the phone so that only its own block of dumpsys user leaves."""
        block = self.sh("dumpsys user | awk '/UserInfo\\{/{p=index($0,\"UserInfo{%d:\")>0} p'" % self.user, timeout=20)
        return set(re.findall(r"\b(no_[a-z_]+)\b", block))

    def after_reboot(self, timeout=None):
        """Wait for boot, then until the experiment user is in the foreground and unlocked (user 0 on AWS; on a personal
        phone the user switches back to P06 Test). The driver never unlocks or switches users."""
        pause = os.environ.get("P06_FG_PAUSE_FILE")
        try:
            self.wait_boot()
            if self.emulator:
                return
            timeout = timeout or (600 if self.aws else 1800)   # AWS: user 0 comes back by itself; do not burn minutes
            print("rebooted: waiting for user %s in the foreground and unlocked" % self.user, flush=True)
            t0 = time.time()
            while time.time() - t0 < timeout:
                try:
                    if self.current_user() == self.user and "RUNNING_UNLOCKED" in self.sh("am get-started-user-state %d" % self.user):
                        return
                except Exception:
                    pass
                time.sleep(5)
            raise GuardError("user %s was not back in the foreground within %d s after the reboot" % (self.user, timeout))
        finally:
            if pause and os.path.exists(pause):
                os.remove(pause)

    def provision(self, pkg_apks):
        """Install P06 apps in the test user, grant what they need there, and tell each app which sources it must not
        touch (files/p06_exclude). Returns install records. pkg_apks: [(package, apk path)]."""
        recs = []
        for pkg, apk in pkg_apks:
            r = self.install(apk)
            if self.aws and "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in r:   # Device Farm installed its re-signed copy
                self.sh(self.u("pm uninstall %s" % pkg)); r = self.install(apk)
            recs.append({"pkg": pkg, "apk": str(apk), "result": r.strip()[-200:]})
            if "Success" not in r:
                raise RuntimeError(recs)
            self.sh(self.u("appops set %s MANAGE_EXTERNAL_STORAGE allow" % pkg))
            if "sms" not in self.excluded:
                self.sh(self.u("appops set %s WRITE_SMS allow" % pkg))
            for p in PERMS:
                if PERM_SOURCE.get(p) not in self.excluded:
                    self.sh(self.u("pm grant %s android.permission.%s" % (pkg, p)))
            if self.excluded:
                self.app_sh(pkg, "mkdir -p files && echo %s > files/p06_exclude" % " ".join(sorted(self.excluded)))
                self.sh(self.u("am force-stop %s" % pkg))   # next start reads the exclusion file
        return recs

    # ---------- app sandbox ----------
    def app_sh(self, pkg, cmd, timeout=60):
        """Run cmd in pkg's data directory, as root on the emulators or as the app's uid (run-as) in the test user."""
        if self.rooted and self.emulator:
            return self.sh("cd /data/data/%s && %s" % (pkg, cmd), timeout=timeout)
        return self.sh(self.u("run-as %s sh -c '%s'" % (pkg, cmd.replace("'", "'\\''"))), timeout=timeout)

    def cat(self, pkg, rel):
        return self.app_sh(pkg, "cat %s 2>/dev/null" % rel)

    def rm(self, pkg, rel):
        return self.app_sh(pkg, "rm -f %s" % rel)

    def kill9(self, pkg):
        """SIGKILL the app process. The shell uid cannot signal an app uid on a production build; run-as can."""
        p = self.pid(pkg)
        if p:
            if self.rooted and self.emulator:
                self.sh("kill -9 %s" % p)
            else:
                self.app_sh(pkg, "kill -9 %s" % p)
        return p

    def freezer_on(self):
        """AWS only. Some Device Farm Pixel 8 units run with the cached-apps freezer off (`use_freezer=false` in
        `dumpsys activity settings`; B1 runs 106d9bc0, 5ec38290), others on (B0 runs, diagnosis run 270a7324). Turn it on
        through the global setting the freezer observes at runtime (no reboot, which Device Farm forbids) and read it
        back. campaign.py restores the setting from its snapshot at the end of the run."""
        use = lambda: (re.findall(r"use_freezer=(\w+)", self.sh("dumpsys activity settings | grep use_freezer")) or ["?"])[0]
        rec = {"use_freezer_before": use(), "setting_before": self.sh("settings get global cached_apps_freezer").strip()}
        if rec["use_freezer_before"] != "true":
            self.sh("settings put global cached_apps_freezer enabled"); time.sleep(2)
        rec["use_freezer_after"] = use()
        rec["turned_on"] = rec["use_freezer_before"] != "true" and rec["use_freezer_after"] == "true"
        return rec

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
                          "fingerprint": g("ro.build.fingerprint"), "sdk": g("ro.build.version.sdk"),
                          # which physical unit and which Device Farm run (a run may land on another unit of the model)
                          "device_instance": os.environ.get("DEVICEFARM_DEVICE_UDID") if self.aws else self.s,
                          "device_arn": os.environ.get("DEVICEFARM_DEVICE_ARN") if self.aws else None,
                          "run_arn": os.environ.get("DEVICEFARM_RUN_ARN") if self.aws else None,
                          "user_id": self.user, "excluded_sources": sorted(self.excluded),
                          "user_no_sms": "no_sms" in self.restrictions,
                          "user_no_outgoing_calls": "no_outgoing_calls" in self.restrictions}
        return dict(self._meta, serial=self.s, rooted=self.rooted, plugged=self.plugged())

    def now_ms(self):
        return int(self.sh("date +%s%3N").strip())

    def wait_boot(self, timeout=300):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if self.sh("getprop sys.boot_completed", timeout=10).strip() == "1":
                    return time.time() - t0
            except GuardError:
                raise
            except Exception:
                pass
            time.sleep(2)
        raise RuntimeError("boot timeout")

    def pid(self, pkg=CPKG):
        if self.emulator:
            return self.sh("pidof %s" % pkg).strip()
        # only the process of the test user (uid = user * 100000 + app id), never another user's copy
        for line in self.sh("for p in $(pidof %s); do echo $p $(stat -c %%u /proc/$p); done" % pkg).splitlines():
            p = line.split()
            if len(p) == 2 and p[1].isdigit() and int(p[1]) // 100000 == self.user:
                return p[0]
        return ""

    # ---------- client commands ----------
    def cmd(self, cmd, extra="", timeout=40, pkg=CPKG):
        self.seq += 1
        rid = "%d_%d" % (int(time.time() * 1000) % 10**9, self.seq)
        self.rm(pkg, "files/res_%s.json" % rid)
        self.sh(self.u("am broadcast -n %s/.Cmd --es cmd %s --es id %s %s" % (pkg, cmd, rid, extra)))
        t0 = time.time()
        while time.time() - t0 < timeout:
            out = self.cat(pkg, "files/res_%s.json" % rid)
            if out.startswith("{"):
                self.rm(pkg, "files/res_%s.json" % rid)
                return json.loads(out)
            time.sleep(0.15)
        raise TimeoutError("no response to %s %s; run-as diagnosis: %s" % (cmd, rid, json.dumps(self.runas_diag(pkg))))

    def launch(self, pkg=CPKG):
        self.require_fg()
        self.sh(self.u("am start -W -n %s/.Main" % pkg), timeout=60)
        for _ in range(60):
            if self.pid(pkg):
                return True
            time.sleep(0.2)
        return False

    def mut(self, op, a="", b="", extra="", timeout=20):
        """Mutate shared media/files as another app (org.leasemem.mut) through MediaStore / FUSE file I/O."""
        self.seq += 1
        rid = "m%d" % self.seq
        self.sh(self.u("am broadcast -f 32 -n org.leasemem.mut/.Cmd --es op %s --es a '%s' --es b '%s' --es id %s %s" % (op, a, b, rid, extra)))
        t0 = time.time()
        while time.time() - t0 < timeout:
            out = self.cat(MPKG, "files/done_%s" % rid)
            if out.startswith("R:"):
                self.rm(MPKG, "files/done_%s" % rid)
                return json.loads(out[2:])
            time.sleep(0.1)
        raise TimeoutError("mut %s; run-as diagnosis: %s" % (op, json.dumps(self.runas_diag(MPKG))))

    def runas_diag(self, pkg):
        """After an app command got no answer: why can the shell not read the app's files? run-as prints its errors on
        stderr, which sh() drops, so `2>&1` folds them in on the device. Read-only; never raises."""
        out = {}
        for c in [self.u("run-as %s id" % pkg) + " 2>&1", "run-as %s id 2>&1" % pkg,
                  self.u("run-as %s ls -la files" % pkg) + " 2>&1", "getprop ro.debuggable", DUMP_PKG % pkg]:
            try:
                r = self.sh(c, timeout=30, retries=0)
                if c.startswith("dumpsys"):     # only the package flags (DEBUGGABLE) and the code path
                    r = " ".join(re.findall(r"(?:pkgFlags|flags|codePath)=\S[^\n]*", r)[:4])
                out[c] = r.strip()[:400]
            except Exception as e:
                out[c] = "%s: %s" % (type(e).__name__, str(e)[:300])
        print("run-as diagnosis for %s: %s" % (pkg, json.dumps(out)), flush=True)
        return out

    def home(self):
        self.require_fg()
        self.sh("input keyevent KEYCODE_HOME")

    def trig_log(self):
        return self.cat(TPKG, "files/trig.log")

    def trig_log_clear(self):
        self.app_sh(TPKG, ": > files/trig.log")

    def trig_cmd(self, cmd):
        self.sh(self.u("am broadcast -n %s/.Cmd --es cmd %s" % (TPKG, cmd)))


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
NAME = "vnd.android.cursor.item/name"


class World:
    """Ground-truth-tracking mutator. Mutations are performed by a separate app (org.leasemem.mut) through public
    Android APIs; every mutation records what it did and the device time before/after. self.kinds leaves out the
    sources the device excludes (SMS, and the call log unless it is proven separate, on the personal phone)."""

    KINDS = {"contacts": ["update", "delete", "insert"], "sms": ["insert", "update", "delete"],
             "calllog": ["insert", "update", "delete"], "media": ["insert", "update", "delete"],
             "calendar": ["update", "delete", "insert"], "settings": ["update"],
             "files": ["update", "insert", "delete"]}

    def __init__(self, dev, rng):
        self.d = dev
        self.r = rng
        self.n = 0
        self.kinds = {s: k for s, k in self.KINDS.items() if s not in dev.excluded}

    def ensure_base(self):
        r = self.d.mut("ensure")
        if not r.get("ok"):
            raise RuntimeError("ensure failed: %s" % r)
        return r

    def mutate(self, src, kind):
        if src in self.d.excluded:
            raise GuardError("source %s is excluded on this device" % src)
        self.n += 1
        tag = "%d%03d" % (int(time.time()) % 100000, self.n % 1000)
        r = self.d.mut("mutate", src, kind, extra="--es tag %s" % tag)
        if not r.get("ok"):
            raise RuntimeError("mutate failed: %s %s %s" % (src, kind, r))
        return {"src": src, "kind": kind, "tag": tag, "t_pre": r["t_pre"], "t_dev": r["t_post"], "did": r.get("did")}
