# MIUI / 澎湃OS 计步链路笔记

小米手机上"步数"这件事，被拆在四个不同的地方：传感器、系统服务、数据库、ContentProvider，
最后还要经过 App 和它的服务端。这份笔记把它们串成一条线，并给出一份**只读**诊断脚本。

- 实测环境：Redmi Turbo 4（`rodin` / `24129RT7CC`），HyperOS `OS2.0.103.0.VOJCNXM`，Android 15，kernel `6.6.30`
- 结论都标了证据等级，没验证过的会明说

---

## 一、这个仓库是干什么的

**解决四类具体问题：**

| 你遇到的 | 这里能给你 |
|---|---|
| 走了很多路，步数不涨/不涨够 | 知道卡在哪一层，用一命令确认是"没落库"还是"App 没读" |
| 改了数据，App 里毫无反应 | 看懂 App 读的是哪份数据（很多 App 有自己的一份） |
| 排行榜数字对不上 | 明白排行榜读的是**服务端**，本地改动不会回滚服务端 |
| 想知道"谁能看到我的步数" | 列出实际持有 `READ_STEPS` 权限的 App |

**它不做什么：**

- 不提供改步数的成品工具（只讲机制，附只读诊断）
- 不涉及破解、不篡改系统分区
- 不保证换机型/换系统版本后仍然成立——每次先跑诊断脚本确认

---

## 二、一句话结论

> 手机里的"今日步数"不是一个数字，而是一条**流水线**。
> 你在某一层看到的数变了，不代表下一层也跟着变。

最常见的困惑"我改了步数，排行榜没动"，答案就在这条链的最后两跳：
**App 有自己的拉取节奏，排行榜又由服务端决定。**

---

## 三、原理：四层 + 一跳

```
① 传感器          step_count(19) / step_detect(18)
   硬件             需要 ACTIVITY_RECOGNITION
        │ 开机以来的累计值
        ▼
② 系统步数服务     system_server 里的 StepCounterManagerService
   谁在管          Delay=300s（自动刷新） Record Delay=30s（记录粒度）
        │ 按节奏落库
        ▼
③ 数据库           /data/data/com.miui.rom/databases/Steps.db
   存什么          StepsTable(_id,_begin_time,_end_time,_mode,_steps)
        │ 对外提供
        ▼
④ ContentProvider  content://com.miui.providers.steps/item
   谁能读          miui.permission.READ_STEPS（签名级白名单）
        │
        ▼
⑤ App → 服务端     小米健康 / 微信 / 支付宝 / QQ
                   App 自己决定何时读、何时上报；排行榜以服务端为准
```

### 每一层谁说了算

| 层 | 归谁 | 延迟特性 |
|---|---|---|
| ① 传感器 | 硬件 + 传感器 HAL | 实时 |
| ② 服务 | `system_server` | **受 `Delay` 控制，默认 300 秒一批** |
| ③ 数据库 | 上面的服务写入 | 跟随服务节奏 |
| ④ Provider | `com.miui.rom` 的 `StepProvider` | 查询即时，返回当前库里的值 |
| ⑤ App / 服务端 | 各家自己 | **手机端无法控制** |

**所以"能优化的"只有中间两跳**。想知道具体怎么触发，见
[`docs/cmd-interface.md`](docs/cmd-interface.md)（系统有一个未公开的 cmd 接口，可以强制落库、调整刷新间隔）。

---

## 四、几个反常识的实测结论

| 结论 | 依据 |
|---|---|
| **root 也读不了 Provider** | 它校验的是权限不是 uid；`content query` 直接 `SecurityException` |
| **shell 反而能看全部步数** | `dumpsys miui_step_counter_service` 无需任何权限，输出今日总量 + 逐段历史 |
| **小米健康显示的不是这个库的数** | 它有自己的一套缓存（Realm + MMKV），改库后首页数字可能不动 |
| **微信自己也订阅传感器** | `dumpsys sensorservice` 里 `com.tencent.mm.plugin.sport` 有 60+ 处订阅 |
| **排行榜是服务端数据** | 本地改完当天能上榜；把本地还原后，服务端的记录不会跟着回滚 |

---

## 五、快速开始

需要 `adb` 可用、手机连上（root 可选，只影响能否导出数据库）。

```bash
python scripts/diagnose.py          # 基础体检
python scripts/diagnose.py --db     # 额外导出 Steps.db 并统计（需要 root）
```

输出示例：

```
[设备]   24129RT7CC / rodin / OS2.0.103.0.VOJCNXM / Android 15
[传感器] step_count(19)、step_detect(18)
[服务]   Delay=300s  RecordDelay=30s  Today Total=3131（walk 3131）
[片段]   17:24:40-17:24:44  15 步
[权限]   shell 查询 Provider → 拒绝（miui.permission.READ_STEPS）
[持有]   小米运动健康 / 微信 / 支付宝 / QQ
```

---

## 六、文档索引

| 文件 | 讲什么 |
|---|---|
| [`docs/data-flow.md`](docs/data-flow.md) | 五段链路的逐层详解：谁写、谁读、延迟卡在哪、证据是什么 |
| [`docs/cmd-interface.md`](docs/cmd-interface.md) | 未公开的 `cmd miui_step_counter_service` 接口全表 + 实测输出 + 语义 |
| [`docs/provider.md`](docs/provider.md) | Provider 的 URI、列名、mode 取值、权限模型、三种读取方式 |
| [`docs/faq.md`](docs/faq.md) | 10 个高频问题，每条都附"自己怎么验证" |

---

## 七、标记约定

文中每个结论都带一个标记，方便你判断可信度：

| 标记 | 含义 |
|---|---|
| 【实测】 | 在本文档顶部的设备上真跑过、看过输出 |
| 【源码】 | 从 APK/JAR/dumpsys 行为推断，未逐行验证 |
| 【官方】 | 小米开发者文档里写明 |
| 【社区】 | 网上说法，**未独立验证**，仅供参考 |

---

## 八、免责声明

- 本项目是**技术记录 + 只读诊断**，不含任何修改步数的成品工具。
- 修改健康数据可能违反第三方平台（微信运动、支付宝运动等）的用户协议，后果自负。
- 私有接口随系统版本变化，换机型/版本前请先跑诊断脚本确认。
- 仅在自己的设备上使用。

MIT License.