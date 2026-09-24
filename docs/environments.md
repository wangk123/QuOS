# QuOS · 环境信息

> 内部环境连接信息，供开发部署使用。本文件入 git，仅存放内网测试凭证；若仓库转公开需先清理。

## MySQL（元数据索引库）

QuOS 采用「文件为源 + MySQL 索引」架构：需求资产（材料/md/git 仓库）全部在文件系统 `server/data/<slug>/`，MySQL 只存可重建的元数据索引（见 `docs/specs/2026-09-24-project-mgmt-design.md`）。库丢失无损，扫描目录即可 rebuild。

| 项 | 值 |
| --- | --- |
| Host | 192.168.17.216 |
| Port | 3306 |
| 版本 | 8.0.46 |
| 登录账号 | perftest / perftest（仅有 perftest 库权限） |
| QuOS 库名 | `quos`（专用，不与既有 `perftest` 库混用） |

### 建库（已于 2026-09-24 用管理员账号执行完毕，勿重复）

```sql
CREATE DATABASE IF NOT EXISTS quos CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON quos.* TO 'perftest'@'%';
FLUSH PRIVILEGES;
```

`projects` 表已按 spec §3 建好（见 `docs/specs/2026-09-24-project-mgmt-design.md`）。管理员账号凭证不入此文档，应用只用 perftest。

### 应用连接配置（环境变量，start.sh / .env）

```
QUOS_DB_HOST=192.168.17.216
QUOS_DB_PORT=3306
QUOS_DB_USER=perftest
QUOS_DB_PASSWORD=perftest
QUOS_DB_NAME=quos
```

## LLM API

- 真实模式：`QUOS_LLM_API_KEY` / `QUOS_LLM_BASE_URL` / `QUOS_LLM_MODEL`（OpenAI 兼容接口）
- 假数据模式：`QUOS_FAKE_AI=1`（无需 key，`app/ai/fake.py` 固定假数据）
- 见 `start.sh` 头部注释
