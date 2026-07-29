# Master Key 紧急离线重加密

本文只适用于 Master Key 疑似泄漏、文件损坏但仍有可用备份，或受控恢复演练。
平台不实行 Master Key 有效期、定期轮换、在线多 Key keyring，也不提供 Web
查看、下载、编辑或轮换入口。

## 硬性前提

- 安排完整维护窗口；停止 API、Internal API Platform、Agent Worker、Job/Delivery
  Dispatcher、Webhook、DingTalk 与 Attachment 服务，只保留 PostgreSQL；
- 先确认 Job、Job Dispatch、Delivery 与 Webhook Outbox 已排空或已记录精确状态；
- 对 PostgreSQL 做可恢复备份，并分别备份旧 Master Key 文件；
- 新 Key 必须在隔离环境生成，使用
  `EA_MASTER_KEY_V1:<32-byte-canonical-base64url>` 格式和 `0400` 权限；
- 记录维护 operation ID、数据库备份引用、旧/新 Key 文件保管人和审批记录，
  但不得记录 Key 内容、可逆摘要、Secret 明文、nonce 或 ciphertext；
- 不得在业务容器运行期间执行，不得通过 Web、HTTP API、数据库控制台或聊天
  粘贴 Key/Secret。

## 停机前只读核验

以下查询只统计 metadata，不输出密文：

```sql
select status, count(*)
from platform_secret
group by status
order by status;

select algorithm, status, count(*)
from platform_secret_version
group by algorithm, status
order by algorithm, status;

select count(*) as missing_active_version
from platform_secret s
left join platform_secret_version v
  on v.secret_id = s.id
 and v.version = s.active_version
 and v.status = 'active'
where s.status = 'enabled'
  and v.id is null;
```

`missing_active_version` 必须为 0。保存 Secret 数量、版本数量和算法分组，不保存
查询出的 `ciphertext`、`nonce` 或 `key_id`。

## 离线批量重加密

离线维护程序必须是一次性、经过代码复核的受控程序，不得复用在线 Web 进程。
它必须在一个数据库事务中完成以下操作：

1. 从两个独立的只读文件分别加载旧 Key 和新 Key，并执行与启动流程相同的格式/
   权限检查；
2. 锁定 `platform_secret` 与 `platform_secret_version`，再次核对停机前数量；
3. 逐行读取版本；对 `AES-256-GCM-AAD-V1` 使用
   `platform-secret|v1|<secret_id>|<version>` 作为 AAD，对历史
   `AES-256-GCM` 版本仅按原算法解密；
4. 使用旧 Key 解密后立即用新 Key、全新随机 12-byte nonce 和
   `AES-256-GCM-AAD-V1` 重加密；明文只存在于当前循环的内存缓冲区并在每次
   迭代后清零；
5. 只更新 `ciphertext`、`nonce`、`key_id` 与 `algorithm`，不得改变 Secret
   code、ref、version、status、active_version、用途或依赖；
6. 在事务提交前，用新 Key 解密验证每一个新密文，并确认行数、Secret/版本
   关系、唯一 active 版本约束均未变化；
7. 任一行解密、重加密或验证失败时回滚整个事务，不允许部分提交；
   不得同时保留两把在线 Key。

维护程序的标准输出只能包含 operation ID、处理行数、成功/失败状态和固定错误
码。不得打印异常参数、Key、Secret、ciphertext、nonce、连接串或可逆摘要。

## 原子替换与恢复服务

1. 事务成功后，先把新 Key 写到同目录的临时文件，验证格式与 `0400` 权限；
2. 将旧 Key 文件移入受控离线备份位置，再用文件系统原子 rename 把新文件替换
   到 `APP_CONFIG_MASTER_KEY_FILE` 指向的固定路径；
3. 先运行 one-shot Migrator/schema head 校验；
4. 只启动 API 与 Internal API Platform，确认 `/ready` 正常，Secret metadata
   列表可读，且相关资源没有解密错误；
5. 依次启动 Worker、Dispatcher、Webhook、DingTalk 与 Attachment 服务；
6. 检查 `platform_secret_change_event`、资源 readiness 和审计，确认没有 Secret
   明文、密文或 Key 出现在日志/API/Job/tool-call 中；
7. 完成一次受控的数据库、Redis、Loki 与 Connector 只读验证后结束维护窗口。

## 回滚

如果数据库事务未提交，继续使用旧 Key 文件即可；不得替换文件。

如果事务已提交但新 Key 启动验证失败：

1. 再次停止全部业务服务；
2. 整库恢复维护前 PostgreSQL 备份；
3. 原子恢复与该数据库备份配对的旧 Master Key 文件；
4. 重新执行 schema head 和只读 Secret/资源核验；
5. 在查清失败原因前不得再次尝试重加密。

禁止只恢复数据库或只恢复 Key；两者必须作为配对恢复单元。
