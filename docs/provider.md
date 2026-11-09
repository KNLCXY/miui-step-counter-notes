# ContentProvider：`com.miui.providers.steps`

> 小米把"步数"包装成一个对外 Provider。名字看起来普通，权限模型却很硬：
> **root 都读不了**。

---

## 一、基本信息

【实测】

```
$ adb shell dumpsys package com.miui.rom | grep -A2 'ContentProvider Authorities:'
  [com.miui.providers.steps]:
    Provider{82d23f2 com.miui.rom/miui.stepcounter.StepProvider}
      applicationInfo=ApplicationInfo{fb6a646 com.miui.rom}
```

| 项 | 值 |
|---|---|
| authority | `com.miui.providers.steps` |
| 实现类 | `com.miui.rom/miui.stepcounter.StepProvider` |
| 承载包 | `com.miui.rom`（`/system_ext/framework/framework-ext-res/framework-ext-res.apk`） |
| 典型 URI | `content://com.miui.providers.steps/item` |
| 读取权限 | `miui.permission.READ_STEPS` |
| 写入权限 | `miui.permission.WRITE_STEPS` |
| 权限级别 | signature / privileged / preinstalled（普通 App 授不上） |

【官方】小米主题开发文档用到过同一 URI 与列名：
`content://com.miui.providers.steps/item`，列 `_id,_begin_time,_end_time,_mode,_steps`
（<https://zhuti.designer.xiaomi.com/docs/blog/MiStep.html>）。
澎湃OS 开发者平台的「计步器接口适配说明」也描述了口径（含 mode 取值）：
<https://dev.mi.com/xiaomihyperos/documentation/detail?pId=1603>

---

## 二、列与取值

| 列 | 类型 | 说明 |
|---|---|---|
| `_id` | INTEGER | 自增主键 |
| `_begin_time` | INTEGER | 段开始，**毫秒** epoch |
| `_end_time` | INTEGER | 段结束，**毫秒** epoch |
| `_mode` | INTEGER | 计步模式：`2` = 走路，`3` = 跑步（`0` 表示设备不支持） |
| `_steps` | INTEGER | 该段步数 |

【实测】本机 22,060 条记录中 `_mode` 全为 `2`；单段约 30 秒（与 `Record Delay = 30s` 对应）。

---

## 三、权限模型（最容易被误解的地方）

```
# 以 shell（uid 2000）查询
$ adb shell content query --uri content://com.miui.providers.steps
java.lang.SecurityException: … requires miui.permission.READ_STEPS or miui.permission.WRITE_STEPS

# 以 root（uid 0）查询
$ adb shell su -c 'content query --uri content://com.miui.providers.steps'
java.lang.SecurityException: … requires android.permission.ACTIVITY_RECOGNITION
```

**结论【实测】**：Provider 校验的是**权限**而不是 uid。
`root` 只是"有权限做任何事"的操作系统用户，但它所携带的进程并没有被授予这些运行时/签名权限，
所以照样被拒。

---

## 四、哪些 App 能读

【实测】`dumpsys package <包> | grep READ_STEPS` 显示已授权的：

| 包名 | 应用 |
|---|---|
| `com.mi.health` | 小米运动健康 |
| `com.tencent.mm` | 微信 |
| `com.eg.android.AlipayGphone` | 支付宝 |
| `com.tencent.mobileqq` | QQ |

> 这份名单是 MIUI 侧的白名单，换版本/换机型可能不同，用自己的设备跑一次即可确认。

---

## 五、三种读取方式（按可用性排序）

### 方式 A：`dumpsys`（无需任何权限）【实测】

```bash
adb shell dumpsys miui_step_counter_service | head -20
```

能直接拿到：`Delay` / `Record Delay` / `Today Total steps: N, walk/run/treadmill` / 逐段历史。
**这是最省事的方式**，适合排查与做诊断脚本。

### 方式 B：有 root 时直读数据库【实测】

```bash
adb shell su -c 'cp /data/data/com.miui.rom/databases/Steps.db /data/local/tmp/'
adb pull /data/local/tmp/Steps.db
sqlite3 Steps.db \
  "select date(_begin_time/1000,'unixepoch','localtime') d, sum(_steps)
   from StepsTable group by d order by d desc limit 7"
```

### 方式 C：App 内查询（需要 READ_STEPS）

```kotlin
contentResolver.query(
    Uri.parse("content://com.miui.providers.steps/item"),
    arrayOf("_id", "_begin_time", "_end_time", "_mode", "_steps"),
    "_begin_time >= ?", arrayOf(todayStartMillis.toString()), null
)
```

只有白名单 App 能成功；第三方 App 拿到的是 `SecurityException`。

---

## 六、和数据库的关系

Provider 是"读接口"，数据库是"存储"。两者内容一致，但**读取时机不同**：

- 数据库：服务按 `Delay` 节奏写入（默认 300 秒一批）。
- Provider：查询即时，返回的是**当前数据库里的值**。

所以"刚走完路就查 Provider 查不到"是正常的——还没落库。
`cmd miui_step_counter_service trim-all` 可以强制落库（见 [`cmd-interface.md`](cmd-interface.md)）。
