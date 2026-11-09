#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MIUI / 澎湃OS 计步链路 —— 只读诊断脚本

它只做三件事：读属性、读 dumpsys、看权限。
不会写入数据库、不会改系统参数、不会联网。

用法：
  python diagnose.py            # 基础体检
  python diagnose.py --db       # 额外导出 Steps.db 并统计（需要 root）
  python diagnose.py --serial X84HXGNRAE6LHMKR
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

ADB = os.environ.get("ADB", "adb")
SERIAL = ""
CONSUMERS = {
    "com.mi.health": "小米运动健康",
    "com.tencent.mm": "微信",
    "com.eg.android.AlipayGphone": "支付宝",
    "com.tencent.mobileqq": "QQ",
}


def sh(cmd, timeout=40):
    """执行 adb shell 命令，返回合并后的输出（不抛异常）"""
    args = [ADB] + (["-s", SERIAL] if SERIAL else []) + ["shell", cmd]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return ((r.stdout or "") + (r.stderr or "")).strip()
    except FileNotFoundError:
        print("找不到 adb：请把 platform-tools 加进 PATH，或设置环境变量 ADB")
        sys.exit(2)
    except subprocess.TimeoutExpired:
        return "[超时]"
    except Exception as e:  # noqa: BLE001
        return f"[错误] {e}"


def title(text):
    print()
    print("=" * 58)
    print(text)
    print("=" * 58)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default="", help="目标设备序列号（多设备时指定）")
    ap.add_argument("--db", action="store_true", help="导出 Steps.db 并统计（需要 root）")
    ap.add_argument("--tail", type=int, default=5, help="展示最近几条记录，默认 5")
    args = ap.parse_args()

    global SERIAL
    SERIAL = args.serial

    title("0. 设备连通性")
    devices = sh("echo ok")
    if devices != "ok":
        print("设备不可用：", devices[:200])
        sys.exit(3)
    print("adb shell 正常")

    title("1. 设备信息")
    print("型号      :", sh("getprop ro.product.model"))
    print("代号      :", sh("getprop ro.product.device"))
    print("系统版本  :", sh("getprop ro.build.version.incremental"))
    print("Android   :", sh("getprop ro.build.version.release"))
    print("安全补丁  :", sh("getprop ro.build.version.security_patch"))

    title("2. 传感器")
    sensors = sh("dumpsys sensorservice")
    steps = [ln.strip() for ln in sensors.splitlines() if re.search(r"step_(count|detect)", ln)]
    if steps:
        for ln in steps[:4]:
            print(" ", re.sub(r"\s+", " ", ln)[:120])
    else:
        print("  未发现 step_count / step_detect（可能是不同厂商命名）")

    title("3. 系统步数服务")
    dumps = sh("dumpsys miui_step_counter_service")
    if "Step Counter Manager Service" not in dumps:
        print("  该机型没有 miui_step_counter_service（非 MIUI/澎湃OS？）")
    else:
        for key in ("Delay:", "Record Delay:", "Today Total"):
            for ln in dumps.splitlines():
                if key in ln:
                    print(" ", ln.strip())
                    break
        history = [ln.strip() for ln in dumps.splitlines() if re.match(r"^\d+ Steps:", ln.strip())]
        print(f"\n  最近 {min(args.tail, len(history))} 段：")
        for ln in history[-args.tail:]:
            print("   ", ln[:100])

    title("4. Provider 权限")
    print("  authority: com.miui.providers.steps")
    out = sh("content query --uri content://com.miui.providers.steps")
    if "SecurityException" in out:
        need = "miui.permission.READ_STEPS"
        m = re.search(r"requires ([^\s]+)", out)
        print("  shell 查询 → 拒绝（" + (m.group(1) if m else need) + "）")
    elif out:
        print("  shell 查询 → 有返回（系统可能已放宽限制）")
        print("  ", out.splitlines()[0][:100])
    else:
        print("  shell 查询 → 无输出")

    title("5. 谁持有 READ_STEPS")
    for pkg, name in CONSUMERS.items():
        raw = sh(f"dumpsys package {pkg}")
        if "Unable to find package" in raw or not raw:
            print(f"  {name:<8} {pkg:<28} 未安装")
            continue
        granted = "READ_STEPS: granted=true" in raw.replace(" ", "") or "READ_STEPS:granted=true" in raw.replace(" ", "")
        print(f"  {name:<8} {pkg:<28} {'✅ 持有' if granted else '—'}")

    if args.db:
        title("6. 数据库（需要 root）")
        whoami = sh("su -c id")
        if "uid=0" not in whoami:
            print("  没有 root，跳过")
        else:
            tmp = tempfile.mkdtemp(prefix="steps-db-")
            remote = "/data/local/tmp/_diag_steps.db"
            sh(f"cp -f /data/data/com.miui.rom/databases/Steps.db {remote}; chmod 644 {remote}", timeout=30)
            local = os.path.join(tmp, "Steps.db")
            r = subprocess.run([ADB, "pull", remote, local], capture_output=True, text=True)
            sh(f"rm -f {remote}")
            if not os.path.exists(local):
                print("  导出失败：", (r.stderr or r.stdout).strip()[:160])
            else:
                print("  已导出：", local, f"({os.path.getsize(local)/1024:.0f} KB)")
                try:
                    import sqlite3
                    con = sqlite3.connect(f"file:{local}?mode=ro", uri=True)
                    total = con.execute("select count(*) from StepsTable").fetchone()[0]
                    print("  总记录数：", total)
                    rows = con.execute(
                        "select date(_begin_time/1000,'unixepoch','localtime') d, sum(_steps) s "
                        "from StepsTable group by d order by d desc limit 7").fetchall()
                    print("  最近 7 天：")
                    for d, s in rows:
                        print(f"    {d}  {s:>7} 步")
                    con.close()
                except Exception as e:  # noqa: BLE001
                    print("  解析失败：", e)
            shutil.rmtree(tmp, ignore_errors=True)

    title("完成")
    print("本脚本只读，没有修改任何数据。")
    print("链路说明见 docs/data-flow.md，接口表见 docs/cmd-interface.md。")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    main()