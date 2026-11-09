# MIUI / 澎湃OS 计步链路笔记

> **这个仓库是什么**：一份技术文档 + 一个只读诊断脚本。
> 把小米手机里"步数"从传感器到排行榜的完整链路讲清楚，
> 并记录一组官方没有公开的系统调试接口。
>
> **它不是**：不是 App，也不是开箱即用的一键工具；附了一份**不维护**的示例脚本，
> 只为让你能把文中机制实际跑一遍。

- 实测环境：Redmi Turbo 4（`rodin` / `24129RT7CC`），HyperOS `OS2.0.103.0.VOJCNXM`，Android 15，kernel `6.6.30`
- 每个结论都标了证据等级，没验证过的会明说

---

## 一、它能帮你回答哪些问题

如果你带着下面任意一个问题点进来，这里都有答案：

| 你的问题 | 答案在哪 |
|---|---|
| 走了很多路，步数为什么不涨 / 涨得慢？ | [原理 §四](#四原理四层--一跳)：卡在"没落库"，默认 300 秒一批 |
| 我在系统里看到的数，和 App 里看到的为什么不一样？ | [反常识 §五](#五几个反常识的实测结论)：很多 App 有自己的一份数据 |
| 微信运动排行榜什么时候更新？为什么改了没反应？ | [原理 §四](#四原理四层--一跳)：排行榜读服务端，手机端改不了 |
| 为什么 root 都读不到步数？ | [Provider 权限](docs/provider.md)：它校验权限，不校验 uid |
| 哪些 App 能看到我的步数？ | [Provider 权限](docs/provider.md)：`READ_STEPS` 白名单 |
| 系统里有没有"立即刷新"的开关？ | [私有 cmd 接口](docs/cmd-interface.md)：有，且没人写过文档 |
| 换机型/升级系统后这些还成立吗？ | [FAQ Q9](docs/faq.md)：先跑诊断脚本对比 |

---

## 二、一句话结论

> 手机里的"今日步数"不是一个数字，而是一条**流水线**。
> 你在某一层看到的数变了，不代表下一层也跟着变。

---

## 三、这个仓库包含什么

```
├─ README.md              你正在看的这份：总览 + 原理 + 索引
├─ docs/
│  ├─ data-flow.md        五段链路逐层详解：谁写、谁读、延迟卡在哪、证据是什么
│  ├─ cmd-interface.md    未公开的 cmd miui_step_counter_service 全表 + 实测输出
│  ├─ provider.md         Provider 的 URI、列名、mode 取值、权限模型、三种读取方式
│  └─ faq.md              10 个高频问题，每条附"自己怎么验证"
├─ scripts/
│  └─ diagnose.py         只读诊断：属性 / 传感器 / 服务参数 / 权限 / 可选导出统计
└─ examples/
   └─ step-local/         示例脚本（可写库，不维护；支持多设备 --serial）
```

**适用范围**：Android 逆向与系统调试爱好者、遇到步数不同步问题的小米用户、
想知道"App 到底读的是哪份数据"的开发者。

**不适用**：想要长期可用、随版本更新的成品工具的人——这里的示例脚本明确不维护，坏了不会修。

---

## 四、原理：四层 + 一跳

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

**能优化的只有中间两跳**。怎么触发见 [`docs/cmd-interface.md`](docs/cmd-interface.md)。

---

## 五、几个反常识的实测结论

| 结论 | 依据 |
|---|---|
| **root 也读不了 Provider** | 它校验的是权限不是 uid；`content query` 直接 `SecurityException` |
| **shell 反而能看全部步数** | `dumpsys miui_step_counter_service` 无需任何权限，输出今日总量 + 逐段历史 |
| **小米健康显示的不是这个库的数** | 它有自己的一套缓存（Realm + MMKV），改库后首页数字可能不动 |
| **微信自己也订阅传感器** | `dumpsys sensorservice` 里 `com.tencent.mm.plugin.sport` 有 60+ 处订阅 |
| **排行榜是服务端数据** | 本地改完当天能上榜；把本地还原后，服务端的记录不会跟着回滚 |

---

## 六、快速开始

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

## 七、标记约定

| 标记 | 含义 |
|---|---|
| 【实测】 | 在本文档顶部的设备上真跑过、看过输出 |
| 【源码】 | 从 APK/JAR/dumpsys 行为推断，未逐行验证 |
| 【官方】 | 小米开发者文档里写明 |
| 【社区】 | 网上说法，**未独立验证**，仅供参考 |

---

## 八、免责声明

- `scripts/diagnose.py` 是只读的；`examples/` 下的脚本会改写系统数据库，**用前请先读它自己的 README**。
- 示例脚本不维护、不保证适配你的机型/系统版本。
- 修改健康数据可能违反第三方平台（微信运动、支付宝运动等）的用户协议，后果自负。
- 私有接口随系统版本变化，换机型/版本前请先跑诊断脚本确认。
- 仅在自己的设备上使用。

MIT License.