# 原生验收操作清单

对应 `complete-evidence-collector-acceptance` 的 7.2、7.3、7.5。当前三项均未完成。自动化用例的通过数、辅助脚本启动成功和人工确认文件都不能单独证明原生行为通过。

## 启动与记录

先执行 `npm run check`，指定本机独立 Chrome for Testing 可执行文件和一个**全新输出目录**：

```sh
MES_TEST_CHROME="/实际路径/Google Chrome for Testing" \
MES_TEST_OUTPUT="output/playwright/native-新批次" npm run test:native
```

脚本创建临时 profile，复制 dist 且核对生产 manifest 字节一致，记录 SHA-256。fixture 仅监听本地 4477/4478；脚本正常退出或断言失败时关闭其 Chrome 和 fixture 并删除临时 profile。不要关闭或复用日常 Chrome。已经运行过的目录会被拒绝，避免消费遗留确认。

每次暂停会打印 `NATIVE_STAGE`，并在 `stage.json` 写明操作。操作完成后，在**本次输出目录**创建 `continue-阶段名.json`，例如：

```json
{
  "action": "在根页面链接上右键，选择在新标签页中打开",
  "evidence": "截图路径；或详细记录操作时的菜单文字、目标 URL 和新窗口情况"
}
```

确认文件必须描述已经发生的操作。仅创建文件、`window.open`、`tabs.create`、`permissions.request` 的测试桩或 `debugger.detach` 都不能代替相应原生操作。脚本另外记录实时权限、目标状态、控制页截图到 `native-actions.ndjson` 和 `control-after-*.png`；控制页截图本身不证明原生菜单或弹窗被操作。默认每阶段等待 10 分钟，超时保留 `failure.json` 并退出。

## 当前脚本的阶段

| 阶段 | 实际操作 | 自动核对 |
| --- | --- | --- |
| native-unrelated | 脚本已移动根到独立窗口并通过窗口复选框冻结选择；在该窗口按 Cmd+T / Ctrl+T 并打开指定无关 URL，此时还未开始采集 | 随后的开始范围仍只有冻结的根，无关标签确实存在但未纳入 |
| grant-first-origin | 回到控制页点击开始，Chrome 权限弹窗允许 127.0.0.1 | 根页面已就绪、权限实值、生产 manifest 一致 |
| context-new-tab | 在指定链接右键，选择新标签页 | 唯一目标、父实例、来源证据、同窗、页面与网络就绪 |
| context-new-window | 在指定链接右键，选择新窗口 | 唯一目标、父实例、来源证据、异窗、页面与网络就绪 |
| deny-second-origin | 新会话开始时拒绝新增 localhost 权限 | 已授权根继续，拒绝根无业务事件或请求 |
| cancel-debugger | 点击 Chrome 调试提示条的取消 | 新赋值实际保存、网络不新增、网络/错误 LOST、页面/语义 ACTIVE、控制页降级；随后自动终止并唤醒后台，重复检查拒绝状态 |
| deny-all-origins | 仅选择未授权 localhost 根，点击开始并在真实权限请求中拒绝 | FAILED 诊断会话、失败 UI、无业务事件/请求及合法导出 |
| open-devtools | 在根页实际 F12 / Fn+F12，或浏览器菜单打开 DevTools | 保存打开方式和平台结果；调试中断后执行同一降级与证据检查 |
| close-devtools | 在原生界面关闭 DevTools | 继续保存页面变化、网络保持拒绝，不自行抢回 |

两种右键方式分别保存唯一 marker、首请求服务端到达、真实来源与采集就绪时序，写入 `first-request-timings.json`；不要求首请求零丢失。混合根阶段另自动导航到实际未授权 origin、执行唯一哨兵，再返回并核对新文档基线及未授权区间无业务证据。执行成功时生成并校验 `native-opening.zip`、`native-mixed.zip`、`native-all-failed.zip` 和 `native-devtools.zip`。若 DevTools 打开后没有发生预期的调试中断，应保留实际状态和失败，不用 API 人为制造断开后声称 F12 通过。

## 尚需补齐的组合

当前脚本仍不是完整 7.5 验收器。固定窗口/快捷键、未授权导航返回、全拒绝和取消后后台唤醒已编排但尚未原生实测；根撤回/重新授权与子 frame 原生授权组合还需补充步骤。不得仅凭脚本结束勾选整个任务。

- **固定窗口 + 快捷键（已编排）**：执行开头两个阶段，核对新无关页不被追加。现有 `tabs.create` 自动测试不能替代快捷键组合。
- **撤回与返回**：已授权根采集期间，在浏览器原生权限界面撤回对应站点，观察通道截止和缺口；产生唯一字段/请求哨兵，证明未授权区间无业务证据。重新授权并返回业务页后应建立新的文档/流基线。另验证跳到未授权域名后再返回的路径。
- **子 frame 权限**：先使跨源 frame 未授权，证明未注入且无业务证据；通过真实权限请求授权后检查覆盖文档与可解析基线。撤回子域权限后，原子域业务哨兵不得再进入父统一流，已授权父页应保持或重建有效基线。
- **全部失败（已编排）**：执行 `deny-all-origins`，保留真实弹窗操作和失败包；API 已撤权后的 START 测试不能代替这条原生请求链。
- **后台唤醒后的调试拒绝（已编排）**：取消调试后脚本自动停止并唤醒后台，确认持久化拒绝状态、新页面证据和无自动重连；原生取消仍必须实际操作。

每组保留实际浏览器版本、原生操作记录、权限前后值、目标/文档/流标识、截止前后业务对照及独立校验 ZIP。只有相应任务描述的全部组合实际通过，才更新 OpenSpec 复选框。

## 本次准备检查的边界

历史 `output/playwright/phase8-native-readiness-final/` 到达首次授权等待点。修订脚本的 `output/playwright/phase9-native-readiness/` 使用 `MES_NATIVE_STAGE_TIMEOUT_MS=1500`，预期停在窗口选择后的 `native-unrelated` 等待点；以该目录实际 stage/failure 为准。`manifest-proof.json` 证明未修改 manifest。未执行快捷键或授权，不能计为原生断言通过。原生控制工具本次继续连接超时。

`npm run test:permissions` 是另一套自动化补充：在独立 profile 预授权 fixture 后恢复原始 manifest，使用真实 `permissions.remove` 与后台 START，验证子 frame/根撤权、真实未授权导航返回、后台恢复、混合根与全失败。场景间预授权重置不算会话内重新授权；迟到正文通过暂挂真实读取返回值验证，不冒充磁盘或网络自然延迟。首次重授权请求等待原生弹窗的失败保留在 `phase9-permissions/`，不以自动确认绕过。
