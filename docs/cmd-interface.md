# 私有 cmd 接口：`miui_step_counter_service`

> 这是 MIUI/澎湃OS 给步数服务的**调试接口**。公开资料里没有文档：
> npm 无相关包、GitHub 代码搜索无命中、酷安无对应工具、小米开发者文档未提及。
> 以下内容来自真机 `cmd … --help` 与实测。

---

## 一、命令全表

```
$ adb shell cmd miui_step_counter_service --help
Miui Step Counter manager commands:
  --help|-h
    Print this help text.

  logging-enable
    Enable logging.
  logging-disable
    Disable logging.
  trim-all
    store cache steps to database
  set-delay DELAY
  disable
    set system auto delay value(s).
  set-record-delay DELAY
    set system record delay value(s).
    note: this will affect system the minimum interval for
          recording the number of steps.
```

| 子命令 | 作用 | 实测结果 |
|---|---|---|
| `trim-all` | 把内存里缓存的步数**立刻写进数据库** | `trimAll success!`，随后 `Today Total` 立即从旧值变为最新真实值 |
| `set-delay N` | 设置自动刷新间隔（秒） | `set delay success! current delay is 60s`，`dumpsys` 立即显示 `Delay: 60s, default: 300s` |
| `set-record-delay N` | 设置**记录**的最小间隔（决定一段多长） | 未单独压测；`dumpsys` 显示 `Record Delay: 30s, default: 30s` |
| `disable` | 停用（文档未说明后果） | **未测试**，不建议在主力机上尝试 |
| `logging-enable` / `logging-disable` | 日志开关 | 未测试 |

---

## 二、参数语义

| 参数 | 默认 | 含义 | 影响 |
|---|---|---|---|
| `Delay` | 300s | 自动刷新/缓存落库间隔 | 决定"改了数据多久能被服务感知"，是延迟的主要来源 |
| `Record Delay` | 30s | 记录步数的最小间隔 | 决定数据库里每段记录的粒度（实测就是 30 秒一段） |

`dumpsys` 里总是同时显示 `当前值` 和 `default`：

```
Delay: 300s, default: 300s     ← 改过之后：Delay: 30s, default: 300s
```

---

## 三、典型用法（只读/低风险）

```bash
# 1) 看当前参数与今日总量
adb shell dumpsys miui_step_counter_service | head -12

# 2) 让缓存立刻落库（不改参数）
adb shell cmd miui_step_counter_service trim-all

# 3) 临时加快刷新（例如排查"数据不同步"）
adb shell cmd miui_step_counter_service set-delay 30

# 4) 排查完恢复默认，避免高频写库耗电
adb shell cmd miui_step_counter_service set-delay 300
```

> `set-delay` 是**临时**的：值只影响本次开机周期的运行参数，重启后回到 `default`。

---

## 四、注意事项

1. **`trim-all` 是"落库"不是"上传"**：它只把内存缓存写进 `Steps.db`，不会碰任何服务端。
2. **`set-delay` 太小会增加写库频率**：30s 适合排查，长期用建议回 300s。
3. **`disable` 没有文档**：可能让当日步数停止累计，别在主力机上试。
4. **不同系统版本命令可能不同**：换机型/换版本先跑 `--help` 对比本表。
5. 这些命令**不需要 root**（shell 即可执行），但都属于系统调试入口，请自担风险。

---

## 五、它解决什么问题

| 困惑 | 用这个接口怎么查 |
|---|---|
| "明明走了很多路，步数没变" | 先 `dumpsys` 看 `Today Total`；再 `trim-all` 看是否只是没落库 |
| "数据更新太慢" | `set-delay 30` 临时加快，观察是否改善 |
| "某天记录很碎/很长" | 看 `Record Delay`；它决定单段长度 |
| "改了数据库但 App 没反应" | `trim-all` + 打开对应 App 页面，排查是 App 侧缓存还是服务端延迟 |

链路全貌见 [`data-flow.md`](data-flow.md)。
