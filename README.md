# MIUI / 澎湃OS 计步链路笔记

> 把小米手机上"步数"这件事拆开：数据从传感器到排行榜，中间经过哪几层、每层归谁管、
> 什么能改什么不能改。**只讲机制，不提供成品刷步工具。**

- 环境：Redmi Turbo 4（`rodin` / `24129RT7CC`），HyperOS `OS2.0.103.0.VOJCNXM`，Android 15，kernel `6.6.30`
- 结论基于真机实测 + 反编译/源码对照，凡是没验证过的都会明确标注

---

## 一、一句话结论

> 手机里的"今日步数"不是一个数字，而是**一条流水线**：
> 传感器 → 系统步数服务 → 数据库 → ContentProvider → 各 App → 各家服务端。
> 你在某一层看到的数字变了，不代表下一层也跟着变。

最常见的困惑——"我改了步数，微信排行榜没动"——原因就在这条链的**最后两跳**：
App 有自己的拉取节奏，排行榜又由**服务端**决定。

---

## 二、四层架构

```
┌─────────────────────────────────────────────────────────────┐
│ ① 硬件传感器                                                  │
│    step_count      android.sensor.step_counter(19)  xiaomi    │
│    step_detect     android.sensor.step_detector(18) xiaomi    │
│    权限：android.permission.ACTIVITY_RECOGNITION              │
└───────────────────────────┬─────────────────────────────────┘
                            │ 累计值（开机以来）
┌───────────────────────────▼─────────────────────────────────┐
│ ② 系统步数服务（system_server 内）                             │
│    com.miui.server.stepcounter.StepCounterManagerService     │
│    参数：Delay（自动刷新，默认 300s）/ Record Delay（默认 30s） │
│    私有调试接口：cmd miui_step_counter_service …               │
└───────────────────────────┬─────────────────────────────────┘
                            │ 落库
┌───────────────────────────▼─────────────────────────────────┐
│ ③ 数据库                                                      │
│    /data/data/com.miui.rom/databases/Steps.db                │
│    表 StepsTable(_id,_begin_time,_end_time,_mode,_steps)      │
│    实测：22060 条 / 覆盖 2026-04-09 起，单段约 30 秒           │
└───────────────────────────┬─────────────────────────────────┘
                            │ 对外暴露
┌───────────────────────────▼─────────────────────────────────┐
│ ④ ContentProvider                                             │
│    content://com.miui.providers.steps/item                    │
│    实现：com.miui.rom/miui.stepcounter.StepProvider           │
│    权限：miui.permission.READ_STEPS / WRITE_STEPS（签名级）    │
└───────────────────────────┬─────────────────────────────────┘
                            │ 被读取
                ┌───────────┴────────────┐
                ▼                        ▼
      小米运动健康 / 微信 /          调试通道
      支付宝 / QQ（持 READ_STEPS）   adb shell dumpsys …（无需权限）
```

细节见 [`docs/data-flow.md`](docs/data-flow.md)。

---

## 三、几个"反常识"的实测结论

| 结论 | 证据 |
|---|---|
| **root（uid=0）读不了 Provider** | `content query` 报 `SecurityException`：需要 `ACTIVITY_RECOGNITION`；权限校验看的是**权限**，不是 uid |
| **shell 能看全部步数** | `dumpsys miui_step_counter_service` 无需任何权限，直接输出今日总量 + 逐段历史 |
| **改库会影响一批 App，但不是全部** | 小米健康首页显示的是**它自己算的数**，改库后没跟着变；微信/支付宝会跟着变 |
| **微信自己也读传感器** | `dumpsys sensorservice` 里 `com.tencent.mm.plugin.sport` 有 60+ 处订阅 |
| **排行榜是服务端数据** | 本地改库当天能上榜，但把本地回滚后，**服务端记录不回滚** |

---

## 四、私有 cmd 接口（公开资料里查不到的部分）

```
cmd miui_step_counter_service --help
  trim-all                 立刻把缓存步数写进数据库
  set-delay DELAY          设置自动刷新间隔（默认 300s）
  set-record-delay DELAY   设置记录最小间隔（默认 30s）
  disable                  停用（不建议）
  logging-enable/disable   日志开关
```

完整说明与实测输出见 [`docs/cmd-interface.md`](docs/cmd-interface.md)。

---

## 五、快速开始（只读诊断）

需要：`adb` 可用、手机连上（root 可选，只影响能否导出数据库）。

```bash
python scripts/diagnose.py            # 全量体检
python scripts/diagnose.py --db       # 额外导出 Steps.db 并统计（需要 root）
```

输出示例（节选）：

```
[设备] Redmi Turbo 4 / OS2.0.103.0.VOJCNXM / Android 15
[服务] Delay=300s  RecordDelay=30s
[今日] 3131 步（walk 3131 / run 0 / treadmill 0）
[片段] 21:16:05-21:16:06  12 步
[权限] shell 查询 Provider → 拒绝（需要 miui.permission.READ_STEPS）
```

---

## 六、文档索引

| 文件 | 内容 |
|---|---|
| [`docs/data-flow.md`](docs/data-flow.md) | 四层链路详解：谁写、谁读、延迟在哪 |
| [`docs/cmd-interface.md`](docs/cmd-interface.md) | 私有 cmd 接口全表 + 实测输出 + 语义 |
| [`docs/provider.md`](docs/provider.md) | Provider URI、列名、mode 取值、权限模型 |
| [`docs/faq.md`](docs/faq.md) | 常见问题：不生效、延迟、重复条目、清零 |

---

## 七、标记约定

本文档里每个结论都会带一个标记：

| 标记 | 含义 |
|---|---|
| 【实测】 | 在本机（见顶部环境）跑过命令、看过输出 |
| 【源码】 | 从 APK/JAR/dumpsys 行为推断，未逐行验证 |
| 【官方】 | 小米开发者文档里写明 |
| 【社区】 | 网上说法，**未独立验证**，仅供参考 |

---

## 八、免责声明

- 本项目是**技术记录 + 只读诊断**，不包含任何修改步数的成品工具。
- 修改健康数据可能违反第三方平台（微信运动、支付宝运动等）的用户协议，后果自负。
- 私有接口随系统版本变化，换机型/换版本前请先跑一次诊断脚本确认。
- 仅在自己的设备上使用。

MIT License.