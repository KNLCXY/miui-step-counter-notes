# 示例脚本：`StepLocal.py`

> **定位：示例，不维护。**
> 放在这里的目的是让读者能把文档里的机制**实际跑一遍**，不是提供一个产品。
> 作者不承诺适配新机型/新系统，也不处理你的数据事故。

---

## 它做什么

直接读写 MIUI 的步数数据库，把"今日总步数"补到指定值。

```
/data/data/com.miui.rom/databases/Steps.db
  StepsTable(_id, _begin_time, _end_time, _mode, _steps)
```

做法：**不碰已有记录**，只在今天的空白时段插入合成段（18~45 秒一段、步频 1.4~2.4 步/秒），
让合计等于目标值。写入前自动备份，支持按编号回滚。

---

## 前置条件

| 项 | 要求 |
|---|---|
| 手机 | 已 root（KernelSU / Magisk 等都可），`su` 可用 |
| 电脑 | Python 3.8+，`adb` 在 PATH 中（或设 `ADB` 环境变量指向 adb 可执行文件） |
| 连接 | `adb devices` 能看到设备且为 `device` 状态 |

> 没有 root 只能看，不能改（脚本会提示并退出）。

---

## 用法

```bash
python StepLocal.py status             # 看今日步数、最后一条记录、可用空白段
python StepLocal.py set 20000 --live   # 设成 20000（最后一段落在"现在"）
python StepLocal.py set --live         # 目标随机（默认 16000~22000）
python StepLocal.py add 5000           # 在当前基础上再加 5000
python StepLocal.py lock 20000         # 锁定：真实步数一涨就扣回
python StepLocal.py sync               # 立即落库 + 缩短服务刷新间隔
python StepLocal.py restore-delay      # 恢复默认刷新间隔 300s
python StepLocal.py backups            # 备份列表（带时间）
python StepLocal.py rollback 3         # 回滚到编号 3；省略编号=最新
python StepLocal.py restore            # 等同 rollback 最新
```

Windows 用户直接 `python StepLocal.py ...` 即可，不需要额外的批处理文件。

---

## 内置的几道保险

| 保险 | 说明 |
|---|---|
| 硬上限 | 目标超过 30000 直接拒绝 |
| 只写空白段 | 不动已有真实记录 |
| 容量判断 | 当天过去的时间放不下时，只补能放下的量并提示 |
| 自动备份 | 每次写入前备份到设备 `/sdcard/Download/step-backup/` 与本机 `backups/` |
| 随时回滚 | `rollback <编号>` 按时间点还原 |
| 随机化 | 段长、步频、毫秒位都随机，形态接近真实记录 |

---

## 已知限制（别指望它能长期用）

1. **依赖私有结构**：数据库路径、表名、`cmd miui_step_counter_service` 接口都可能随系统版本变化。
2. **只测过一个版本**：Redmi Turbo 4 / `OS2.0.103.0.VOJCNXM` / Android 15。
3. **不管服务端**：微信运动排行榜由平台决定，脚本只影响手机本地这一层。
4. **不管并发**：写入时若系统正在写库，极小概率冲突；脚本会回读校验，但不做事务级处理。

---

## 免责声明

- 修改健康数据可能违反第三方平台（微信运动、支付宝运动等）的用户协议，**账号风险自负**。
- 脚本按"现状"提供，不附带任何担保。
- 仅在你**自己的设备**上使用。

MIT License，与仓库其余部分一致。
