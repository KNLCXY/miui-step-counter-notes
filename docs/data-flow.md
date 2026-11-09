# 四层链路详解

> 顺序：传感器 → 系统服务 → 数据库 → Provider → App → 服务端。
> 每一层都写清：**谁在管、怎么读、延迟在哪、实测证据是什么**。

---

## ① 硬件传感器

【实测】

```
$ adb shell dumpsys sensorservice | grep -i step
0x00000012) step_detect   | xiaomi | type: android.sensor.step_detector(18) | perm: android.permission.ACTIVITY_RECOGNITION
0x00000013) step_count    | xiaomi | type: android.sensor.step_counter(19)  | perm: android.permission.ACTIVITY_RECOGNITION
```

- `step_counter`（type 19）：返回**开机以来的累计步数**。App 要自己存一个基线，用「当前 − 基线」得到增量。
- `step_detector`（type 18）：每检测到一步触发一次事件。
- 都需要 `ACTIVITY_RECOGNITION` 运行时权限（Android 10+）。

谁在订阅【实测】：

```
$ adb shell dumpsys sensorservice | grep -B2 -A4 'step_count 0x00000013'
  com.miui.server.stepcounter.StepCounterManagerService  uid 1000
  com.android.server.MiuiBatteryIntelligence$…           uid 1000
  com.tencent.mm.plugin.sport.model.a0                   uid 10276   ← 微信自己也在读
```

**要点**：微信不是纯粹"等系统给数"，它自己订阅传感器。所以只改数据库，微信里某些入口仍可能是真实值。

---

## ② 系统步数服务

【实测】

```
$ adb shell dumpsys miui_step_counter_service | head
Step Counter Manager Service(dumpsys miui_step_counter_service)

Delay: 300s, default: 300s
Record Delay: 30s, default: 30s

current step list cache size: 0

step counter database info
Today Total steps: 3131, walk: 3131, run: 0, treadmill: 0
```

- 跑在 `system_server` 里（进程 uid 1000），类名 `com.miui.server.stepcounter.StepCounterManagerService`。
- **两个时间参数**：
  - `Delay`（默认 300s）：缓存落库/刷新的自动间隔 —— 这是"延迟"的主要来源之一。
  - `Record Delay`（默认 30s）：**记录**的最小间隔，决定数据库里一段有多长（实测基本就是 30 秒一段）。
- 有一组**私有 cmd 接口**（`trim-all` / `set-delay` / `set-record-delay`），详见
  [`cmd-interface.md`](cmd-interface.md)。

【实测】把 `Delay` 从 300 改到 60，`dumpsys` 立刻反映；执行 `trim-all` 后，缓存中的真实步数立刻落库。

---

## ③ 数据库

【实测】

```
$ adb shell su -c 'ls -l /data/data/com.miui.rom/databases/Steps.db'
-rw-rw---- 1 u0_a74 u0_a74 581632 ... Steps.db

sqlite> .schema
CREATE TABLE StepsTable(_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        _begin_time INTEGER, _end_time INTEGER,
                        _mode INTEGER, _steps INTEGER);
```

- 实测规模：22,060 条，最早 2026-04-09，单段约 30 秒；`_mode` 观测到全为 `2`（走路）。
- 时间戳是**毫秒** epoch（例：`_begin_time = 1794143835823`）。
- 文件属主是 `u0_a74`（应用 uid），**不是 system**；覆盖时用 `cat > 目标` 可保留 inode 与属主/ SELinux 上下文。

官方文档侧证【官方】：主题开发文档给出的列名与这里完全一致
（`content://com.miui.providers.steps/item`，列 `_id,_begin_time,_end_time,_mode,_steps`）。

---

## ④ ContentProvider

【实测】

```
$ adb shell dumpsys package com.miui.rom | grep -A2 'ContentProvider Authorities'
  [com.miui.providers.steps]:
    Provider{… com.miui.rom/miui.stepcounter.StepProvider}
```

- authority：`com.miui.providers.steps`
- 权限：`miui.permission.READ_STEPS` / `miui.permission.WRITE_STEPS`（签名级，普通 App 授不上）
- 细节与查询方法见 [`provider.md`](provider.md)。

---

## ⑤ App 读取（两条路）

| 路径 | 谁在用 | 能读到什么 |
|---|---|---|
| **A. Provider** | 小米运动健康、微信、支付宝、QQ（实测均持有 `miui.permission.READ_STEPS`） | MIUI 汇总后的今日/分段步数 |
| **B. 传感器** | 任意有 `ACTIVITY_RECOGNITION` 的 App（含微信自身） | 开机以来累计值，自行算增量 |
| **C. Health Connect** | 小米健康声明了 `android.permission.health.WRITE_STEPS` 等 | 跨 App 健康数据 |

【实测】小米健康的主页数字**不等于** Provider 的值：把库改成 20000 时，系统服务显示 20000，
而小米健康首页显示 7914 —— 因为它有自己的 Realm 缓存（`databases/RKStorage` 里有 `"model":"steps"` 的序列）
和 MMKV（`files/mmkv/spf_step_provider`）。**它显示的是自己算/缓存的结果。**

---

## ⑥ 服务端（排行榜）

【实测】时间线（同一天）：

```
21:38  本地库改成 20000       → dumpsys 立刻显示 20000
22:24  微信运动排行榜显示 20000 ← 约 46 分钟后
```

【实测】把本地库回滚后：本地回到 6325，**排行榜仍是 20000** —— 说明排行榜读的是服务端。

【社区】常见说法：微信运动后台约 30 分钟批量同步一次、进页面/下拉可立即触发、当日榜单约 22 点锁定、次日 0 点清零。
**这些说法未独立验证**，但与上面的实测时间线吻合。

---

## 小结：延迟到底在哪

```
传感器        实时
  ↓
系统服务      受 Delay 影响（默认 300s；trim-all 可立即落库）
  ↓
Provider      跟随数据库，查询即时
  ↓
App 读取      各自节奏；打开对应页面通常能触发一次
  ↓
服务端        平台侧决定，无法从手机端强制
```

**能控制的只有中间两跳**；最后两跳由 App 和平台决定。
