# -*- coding: utf-8 -*-
"""MIUI 步数工具（示例脚本，不维护）

!! 免责声明 !!
  这是随笔记一起放出的示例代码，作者不承诺维护、不保证在你的设备上可用。
  它会改写系统数据库 /data/data/com.miui.rom/databases/Steps.db。
  使用前请确认：手机已 root、adb 可用、你愿意承担数据异常/账号风控的后果。

依赖：adb 在 PATH 中（或设置环境变量 ADB 指向 adb.exe）、Python 3.8+
测试环境：Xiaomi/Redmi + HyperOS 2.x + Android 15

命令：
  devices                       列出已连接设备
  status                        查看今日步数 / 最后一条 / 可用空白段
  set 20000                     设为 20000（补在空白时段，直到当前时刻）
  set --live                    目标随机取 MIN_STEP~MAX_STEP
  add 5000                      在当前基础上再加
  lock 20000                    锁定：真实步数一涨就扣回
  sync                          立即落库 + 缩短服务刷新间隔
  restore-delay                 恢复默认刷新间隔 300s
  backups                       备份列表（带时间）
  rollback [编号]                回滚到指定备份，省略=最新
  restore                       等同 rollback 最新

多设备：所有命令都支持 --serial <序列号>，或 -s <序列号>。

原理与链路说明见仓库 README 与 docs/。
"""
import datetime
import re
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import time

ADB = os.environ.get("ADB", "adb")
SERIAL = ""
HERE = os.path.dirname(os.path.abspath(__file__))
TMP_LOCAL = os.path.join(HERE, "_work.db")
DEVICE_DB = "/data/data/com.miui.rom/databases/Steps.db"
BACKUP_DIR_DEVICE = "/sdcard/Download/step-backup"
BACKUP_DIR_LOCAL = os.path.join(HERE, "backups")

# 目标步数约束
DEFAULT_MIN = 16000      # 不指定目标时，随机区间下限
DEFAULT_MAX = 22000      # 随机区间上限
HARD_MAX = 30000         # 硬上限：超过直接拒绝，避免离谱数值

os.makedirs(BACKUP_DIR_LOCAL, exist_ok=True)


# ---------------- adb ----------------
ADB_RAW = ("pull", "push", "devices", "install", "uninstall", "shell", "connect", "disconnect")


def adb(*args, su=False, timeout=60):
    """默认把参数当作设备上的 shell 命令；pull/push 等直接透传。"""
    parts = list(args)
    base = [ADB] + (["-s", SERIAL] if SERIAL else [])
    if su:
        cmd = base + ["shell", "su -c '" + " ".join(parts) + "'"]
    elif parts and parts[0] in ADB_RAW:
        cmd = base + parts
    else:
        cmd = base + ["shell", " ".join(parts)]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def list_devices():
    """返回 [(serial, state), …]"""
    try:
        r = subprocess.run([ADB, "devices"], capture_output=True, text=True, timeout=20)
    except Exception:
        return []
    out = []
    for line in (r.stdout or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
    return out


def cmd_devices():
    devs = list_devices()
    if not devs:
        print("没有检测到设备：请确认 USB 连接、已开启 USB 调试并授权本机")
        return
    print(f"检测到 {len(devs)} 台设备：")
    for i, (serial, state) in enumerate(devs, 1):
        mark = " ← 当前" if serial == SERIAL else ""
        print(f"  {i}. {serial}  [{state}]{mark}")
    if len(devs) == 1:
        print("\n只有一台，直接用即可；多设备时用 --serial 指定，例如：")
        print(f"  python StepLocal.py status --serial {devs[0][0]}")
    else:
        print("\n用 --serial 指定目标，例如：")
        print(f"  python StepLocal.py status --serial {devs[0][0]}")


def pick_device(serial=None):
    """确定要操作的设备：显式指定 > 唯一设备 > 交互选择"""
    global SERIAL
    devs = [d for d, st in list_devices() if st == "device"]
    if serial:
        if serial not in devs:
            print(f"!! 设备 {serial} 不在线（在线：{', '.join(devs) or '无'}）")
            sys.exit(2)
        SERIAL = serial
        return
    if len(devs) == 1:
        SERIAL = devs[0]
        return
    if not devs:
        print("!! 没有可用设备")
        sys.exit(2)
    print("检测到多台设备：")
    for i, d in enumerate(devs, 1):
        print(f"  {i}. {d}")
    try:
        idx = int(input("选择设备编号: ").strip())
        SERIAL = devs[idx - 1]
    except Exception:
        print("!! 输入无效")
        sys.exit(2)


def read_total():
    r = adb("dumpsys miui_step_counter_service", timeout=40)
    m = re.search(r"Today Total steps: (\d+)", (r.stdout or "") + (r.stderr or ""))
    return m.group(1) if m else "(读取失败)"


def need_root():
    r = adb("id", su=True, timeout=20)
    out = (r.stdout or "") + (r.stderr or "")
    if "uid=0" not in out:
        print("!! 没有 root：请先运行 Root.bat / 注入 KernelSU，再执行本工具")
        sys.exit(2)


def pull_db():
    adb(f"cp -f {DEVICE_DB} /data/local/tmp/step_tool.db; chmod 644 /data/local/tmp/step_tool.db", su=True)
    r = adb("pull", "/data/local/tmp/step_tool.db", TMP_LOCAL)
    if not os.path.exists(TMP_LOCAL):
        print("!! 拉取数据库失败：", (r.stderr or r.stdout).strip()[:200])
        sys.exit(3)


def push_db():
    adb("push", TMP_LOCAL, "/data/local/tmp/step_tool_new.db")
    adb(f"rm -f {DEVICE_DB}-journal; "
        f"cat /data/local/tmp/step_tool_new.db > {DEVICE_DB}", su=True)


def backup():
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    adb(f"mkdir -p {BACKUP_DIR_DEVICE}; cp -f {DEVICE_DB} {BACKUP_DIR_DEVICE}/Steps.db.{stamp}", su=True)
    local = os.path.join(BACKUP_DIR_LOCAL, f"Steps.db.{stamp}")
    for _ in range(3):
        adb("pull", f"{BACKUP_DIR_DEVICE}/Steps.db.{stamp}", local)
        if os.path.exists(local) and os.path.getsize(local) > 100000:
            break
        time.sleep(0.5)
    return local


# ---------------- 数据 ----------------
def today_bounds():
    d = datetime.date.today()
    return (int(datetime.datetime.combine(d, datetime.time.min).timestamp() * 1000),
            int(datetime.datetime.combine(d, datetime.time.max).timestamp() * 1000))


def open_db():
    con = sqlite3.connect(TMP_LOCAL)
    return con


def today_rows(con):
    s, e = today_bounds()
    return list(con.execute(
        "select _id,_begin_time,_end_time,_mode,_steps from StepsTable "
        "where _begin_time between ? and ? order by _begin_time", (s, e)))


def today_total(con):
    s, e = today_bounds()
    return con.execute(
        "select coalesce(sum(_steps),0) from StepsTable where _begin_time between ? and ?",
        (s, e)).fetchone()[0]


def find_gaps(rows, min_minutes=5, start_hour=None):
    """返回今天可用于插入的空白时段 [(start_ms, end_ms)]"""
    now = datetime.datetime.now()
    if start_hour is None:
        start_hour = 0 if now.hour < 9 else 8
    day0 = datetime.datetime.combine(datetime.date.today(), datetime.time(start_hour))
    s, e = today_bounds()
    cursor = max(int(day0.timestamp() * 1000), s)
    end_now = int(now.timestamp() * 1000)
    gaps = []
    for r in rows:
        b, en = r[1], r[2]
        if b - cursor > min_minutes * 60000:
            gaps.append((cursor, min(b, end_now)))
        cursor = max(cursor, en)
    if end_now - cursor > min_minutes * 60000:
        gaps.append((cursor, end_now))
    return [(a, b) for a, b in gaps if b - a > 60000]


def make_segments(gaps, need, live=False):
    """把 need 步分摊到 gaps。每段 18~45 秒、步频 1.4~2.4 步/秒，时间精确到秒/毫秒。"""
    if need <= 0:
        return []

    # 每段占用约 30 秒（含 2~15 秒间隙），据此估算每个 gap 的容量
    caps = [max(1, (b - a) // 30000) for a, b in gaps]
    total_cap = sum(caps)

    alloc = [0] * len(gaps)
    if live and len(gaps) > 1:
        alloc[-1] = min(int(need * 0.12), caps[-1] * 55)
    rest = need - sum(alloc)
    for i, c in enumerate(caps):
        alloc[i] += int(rest * c / total_cap)

    rows = []
    for (a, b), amount in zip(gaps, alloc):
        # 起点随机偏移 1~4 分钟，避免整齐
        t = a + random.randint(60, 240) * 1000 + random.randint(0, 999)
        left = amount
        while left > 0 and t < b - 40000:
            dur = random.randint(18, 45)                 # 秒
            rate = random.uniform(1.4, 2.4)              # 步/秒（约 84~144 步/分钟）
            seg = max(1, int(dur * rate))
            if seg > left:
                seg = left
            end = t + dur * 1000 + random.randint(0, 999)
            rows.append((int(t), int(end), 2, int(seg)))
            left -= seg
            t = end + random.randint(2, 15) * 1000       # 段间空隙 2~15 秒

    # 误差补齐（可能多也可能少）
    diff = need - sum(r[3] for r in rows)
    if diff > 0 and rows:
        # 只允许最后一段少量补齐，避免出现"1 分钟 5000 步"这种假数据
        add = min(diff, 200)
        bb, ee, mm, ss = rows[-1]
        rows[-1] = (bb, ee, mm, ss + add)
    elif diff < 0 and rows:
        bb, ee, mm, ss = rows[-1]
        rows[-1] = (bb, ee, mm, max(1, ss + diff))
    rows.sort()
    return rows


# ---------------- 命令 ----------------
def cmd_status():
    need_root()
    pull_db()
    con = open_db()
    rows = today_rows(con)
    total = today_total(con)
    last = rows[-1] if rows else None
    print(f"今日步数   : {total}")
    print(f"今日记录数 : {len(rows)}")
    if last:
        t = datetime.datetime.fromtimestamp(last[2] / 1000).strftime("%H:%M:%S")
        print(f"最后一条   : {t}（{last[4]} 步）")
    gaps = find_gaps(rows)
    print(f"可用空白段 : {len(gaps)} 个")
    for a, b in gaps[:6]:
        f = lambda x: datetime.datetime.fromtimestamp(x / 1000).strftime("%H:%M")
        print(f"   {f(a)} ~ {f(b)}  ({(b-a)//60000} 分钟)")
    con.close()


def do_set(target, live=False):
    need_root()
    pull_db()
    con = open_db()
    cur = today_total(con)
    print(f"当前 {cur} 步 → 目标 {target} 步")
    if cur >= target:
        print("已经达到或超过目标，未做修改（如需降低请用 restore 还原备份）")
        con.close()
        return

    rows = today_rows(con)
    gaps = find_gaps(rows)
    if not gaps:
        print("!! 今天没有可用空白时段，无法插入")
        con.close()
        return

    segs = make_segments(gaps, target - cur, live=live)
    got = sum(s[3] for s in segs)
    print(f"生成 {len(segs)} 段，合计 {got} 步（差 {target-cur-got:+d}）")
    if got < target - cur - 50:
        print(f"!! 今天已过去的时间不够放下 {target-cur} 步，实际只补 {got} 步")
        print("   （凌晨/刚开机时属正常；想补满请等白天再跑一次）")

    bak = backup()
    print("已备份:", bak)

    con.executemany("insert into StepsTable(_begin_time,_end_time,_mode,_steps) values(?,?,?,?)", segs)
    con.commit()
    new_total = today_total(con)
    con.close()

    push_db()
    adb("rm -f /data/local/tmp/step_tool.db /data/local/tmp/step_tool_new.db", su=True)

    print("写入完成，系统服务读到的值：", read_total())
    print(f"（数据库计算值 {new_total}）")


def resolve_target(arg):
    if arg in (None, "", "random", "auto"):
        t = random.randint(DEFAULT_MIN, DEFAULT_MAX)
        print(f"未指定目标，本轮随机 {t} 步（区间 {DEFAULT_MIN}~{DEFAULT_MAX}）")
        return t
    t = int(arg)
    if t > HARD_MAX:
        print(f"!! {t} 超过硬上限 {HARD_MAX}，已拒绝。请用 {DEFAULT_MIN}~{DEFAULT_MAX} 的范围。")
        sys.exit(4)
    if t < 0:
        print("!! 目标不能为负")
        sys.exit(4)
    return t


def cmd_set(arg=None, live=False):
    do_set(resolve_target(arg), live=live)


def cmd_add(n):
    need_root()
    pull_db()
    con = open_db()
    cur = today_total(con)
    con.close()
    do_set(cur + int(n))


def cmd_lock(target):
    print(f"锁定今日步数为 {target}，每 20 秒校正一次，Ctrl+C 退出")
    while True:
        try:
            pull_db()
            con = open_db()
            cur = today_total(con)
            s, e = today_bounds()
            rows = list(con.execute(
                "select _id,_steps from StepsTable where _begin_time between ? and ? and _id > ?",
                (s, e, 0)))
            if cur > target:
                excess = cur - target
                # 只从"今天最后几条"里扣
                for rid, steps in reversed(rows):
                    if excess <= 0:
                        break
                    take = min(steps, excess)
                    excess -= take
                    if steps - take <= 0:
                        con.execute("delete from StepsTable where _id=?", (rid,))
                    else:
                        con.execute("update StepsTable set _steps=_steps-? where _id=?", (take, rid))
                con.commit()
                con.close()
                push_db()
                print(f"[{datetime.datetime.now():%H:%M:%S}] 超出 {cur-target}，已扣回")
            else:
                con.close()
                print(f"[{datetime.datetime.now():%H:%M:%S}] 当前 {cur}，未超")
        except Exception as ex:
            print("轮次异常:", ex)
        time.sleep(20)


def cmd_sync(fast_delay=30):
    """立即落库 + 缩短服务刷新间隔，让 App 尽快读到新值"""
    need_root()
    print("1) 把缓存步数立刻落库 …")
    r = adb("cmd miui_step_counter_service trim-all")
    print("   ", ((r.stdout or "") + (r.stderr or "")).strip()[:120])

    print(f"2) 把自动刷新间隔从 300s 调到 {fast_delay}s …")
    r = adb(f"cmd miui_step_counter_service set-delay {fast_delay}")
    print("   ", ((r.stdout or "") + (r.stderr or "")).strip()[:120])

    d = adb("dumpsys miui_step_counter_service")
    txt = (d.stdout or "") + (d.stderr or "")
    for line in txt.splitlines():
        if "Delay:" in line or "Today Total" in line:
            print("   ", line.strip())

    print("\n3) 现在去手机上触发一次读取：")
    print("   微信 → 微信运动 → 排行榜，往下拉一下")
    print("   或打开「小米运动健康」App")
    print("\n用完记得恢复默认：python StepLocal.py restore-delay")


def cmd_restore_delay():
    need_root()
    r = adb("cmd miui_step_counter_service set-delay 300")
    print(((r.stdout or "") + (r.stderr or "")).strip()[:120])


def parse_stamp(name):
    m = re.search(r"(\d{8})-(\d{6})", name)
    if not m:
        return None
    return datetime.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")


def collect_backups():
    """合并本机与设备上的备份，按时间倒序编号（1 = 最新）"""
    items = []
    if os.path.isdir(BACKUP_DIR_LOCAL):
        for f in os.listdir(BACKUP_DIR_LOCAL):
            if "Steps.db." not in f:
                continue
            p = os.path.join(BACKUP_DIR_LOCAL, f)
            items.append({"name": f, "ts": parse_stamp(f), "size": os.path.getsize(p),
                          "where": "本机", "local": p, "dev": None})
    names = {i["name"] for i in items}
    out = adb(f"ls {BACKUP_DIR_DEVICE}", su=True).stdout or ""
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("Steps.db.") or line in names:
            continue
        dev_path = f"{BACKUP_DIR_DEVICE}/{line}"
        ts = parse_stamp(line)
        size = None
        if ts is None:
            # 旧命名（如 Steps.db.213646）没有日期，用文件修改时间
            st = adb(f"stat -c '%Y %s' {dev_path}", su=True).stdout or ""
            parts = st.split()
            if len(parts) >= 1 and parts[0].isdigit():
                ts = datetime.datetime.fromtimestamp(int(parts[0]))
            if len(parts) >= 2 and parts[1].isdigit():
                size = int(parts[1])
        items.append({"name": line, "ts": ts, "size": size,
                      "where": "设备", "local": None, "dev": dev_path})
    items.sort(key=lambda x: (x["ts"] or datetime.datetime.min), reverse=True)
    for i, it in enumerate(items, 1):
        it["idx"] = i
    return items


def cmd_backups():
    items = collect_backups()
    if not items:
        print("还没有备份（第一次 set 时会自动创建）")
        return
    print(f"{'#':>2}  {'时间':<19}  {'大小':>8}  {'位置':<4}")
    print("-" * 46)
    for it in items:
        t = it["ts"].strftime("%Y-%m-%d %H:%M:%S") if it["ts"] else "?"
        size = f"{it['size']/1024:.0f}KB" if it["size"] else "-"
        note = "  ← 最新" if it["idx"] == 1 else ""
        print(f"{it['idx']:>2}  {t:<19}  {size:>8}  {it['where']:<4}{note}")
    print("\n回滚：rollback <序号>   例：rollback 2")


def cmd_rollback(arg=None):
    need_root()
    items = collect_backups()
    if not items:
        print("!! 没有备份可回滚")
        return
    if arg in (None, "", "latest", "last"):
        pick = items[0]
    else:
        pick = None
        try:
            idx = int(arg)
            pick = next((x for x in items if x["idx"] == idx), None)
        except ValueError:
            pick = next((x for x in items if arg in x["name"]), None)
        if not pick:
            print(f"!! 没有编号为 {arg} 的备份，先运行 backups 查看列表")
            return

    if pick["local"]:
        adb("push", pick["local"], "/data/local/tmp/step_restore.db")
        adb(f"rm -f {DEVICE_DB}-journal; cat /data/local/tmp/step_restore.db > {DEVICE_DB}", su=True)
        adb("rm -f /data/local/tmp/step_restore.db", su=True)
    else:
        adb(f"rm -f {DEVICE_DB}-journal; cat {pick['dev']} > {DEVICE_DB}", su=True)

    t = pick["ts"].strftime("%Y-%m-%d %H:%M:%S") if pick["ts"] else "?"
    print(f"已回滚到 #{pick['idx']}  {pick['name']}")
    print(f"备份时间：{t}   来源：{pick['where']}")
    print("当前步数：", read_total())


def cmd_restore():
    print("（restore 等同于回滚到最新备份）")
    cmd_rollback(None)


def main():
    a = sys.argv[1:]
    serial = None
    cleaned = []
    i = 0
    while i < len(a):
        if a[i] in ("-s", "--serial") and i + 1 < len(a):
            serial = a[i + 1]
            i += 2
            continue
        if a[i].startswith("--serial="):
            serial = a[i].split("=", 1)[1]
            i += 1
            continue
        cleaned.append(a[i])
        i += 1
    a = cleaned

    if not a:
        print(__doc__)
        return
    c = a[0]

    if c in ("devices", "dev"):
        cmd_devices()
        return
    if c not in ("-h", "--help", "help"):
        pick_device(serial)
    if c == "status":
        cmd_status()
    elif c == "set":
        cmd_set(a[1] if len(a) > 1 and not a[1].startswith("--") else None,
                live=("--live" in a))
    elif c == "add":
        cmd_add(a[1])
    elif c == "lock":
        cmd_lock(int(a[1]))
    elif c == "restore":
        cmd_restore()
    elif c in ("sync", "flush"):
        cmd_sync()
    elif c in ("restore-delay", "delay-default"):
        cmd_restore_delay()
    elif c == "rollback":
        cmd_rollback(a[1] if len(a) > 1 else None)
    elif c == "backups":
        cmd_backups()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()