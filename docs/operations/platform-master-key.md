# 平台固定 Master Key

平台 Secret、ONES Challenge/当前个人凭据、短期附件凭据和受管渠道回复凭据使用同一个
固定 Master Key 加密。
Master Key 不属于业务数据库密码，也不得写入仓库、Compose 文件、数据库、
日志、审计或 Web 配置。

## 文件格式

文件必须只有一行：

```text
EA_MASTER_KEY_V1:<32-byte-canonical-base64url>
```

约束：

- payload 解码后必须正好 32 bytes；
- 使用无 `=` padding 的 canonical base64url；
- 普通宿主机文件必须是 regular file、不得为符号链接，权限必须为 `0400`
  或其他 owner-only 模式；
- Docker secret 挂载位于 `/run/secrets` 时必须没有任何写权限；
- 文件最大 256 bytes，可有一个结尾换行。

示例生成方式（只在受控终端执行，命令不打印 Key）：

```bash
install -d -m 700 "$HOME/.config/enterprise-agent"
umask 077
python3 -c 'import base64,secrets,pathlib; p=pathlib.Path.home()/".config/enterprise-agent/app-config-master-key"; p.write_text("EA_MASTER_KEY_V1:"+base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")+"\n"); p.chmod(0o400)'
```

在仓库外 `.env` 或启动环境中配置绝对路径：

```text
APP_CONFIG_MASTER_KEY_FILE=/Users/<user>/.config/enterprise-agent/app-config-master-key
```

Compose 只把该文件只读挂载为 `/run/secrets/app_config_master_key`。非测试
API、Worker 和 tool-mcp 在文件缺失、权限过宽、格式错误时
拒绝启动，不生成临时 Key，也不回退到 `APP_CONFIG_MASTER_KEY` 明文环境变量。

## 备份

- 至少保留两份加密离线备份，分别由不同受控位置保管；
- 备份必须保留文件内容和格式，但不得与数据库备份放在同一未加密介质；
- 每次数据库备份恢复演练都要验证对应 Master Key 可用；
- 不在健康检查、工单或聊天中粘贴 Key、Key 摘要或文件内容；
- 丢失 Master Key 将导致现有平台 Secret 无法恢复。

仓库当前没有覆盖全部密文域的受支持重加密工具。发生泄漏或文件损坏时，先按
[Master Key 紧急离线重加密](./emergency-master-key-reencryption.md) 的顶部警告停机、
隔离和备份；不要执行其中已失效的旧重加密草案。平台不提供 Web 管理、多 Key keyring
或到期策略。

本阶段不设置有效期、不做定期轮换、不提供 Web 查看/下载/编辑能力。
紧急离线重加密流程在 Phase 3A 完成时单独记录。
