# Coorporate Hermes

Coorporate Hermes 是由 [AmpliIA](https://ampliia.com/en/) 维护的单租户企业 AI 助手发行版，基于上游 Hermes Agent 代码库改造，面向公司内部部署：角色化网关会话、受治理的文件夹访问、企业/团队/用户三层记忆与技能、从上游 Hermes 导出包的安全迁移、cron 人工审批检查点，以及企业审计日志。

## 安装

```bash
git clone https://github.com/andreloureiro/coorporate-hermes.git
cd coorporate-hermes
./setup-coorporate.sh
coorporate setup
coorporate
```

开发安装：

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
coorporate --help
```

## 企业治理

生产环境建议启用治理并使用默认拒绝的文件策略：

```yaml
governance:
  enabled: true
  tenant_id: acme-corp
  default_role: viewer
  role_hierarchy: [viewer, operator, manager, admin]
  users:
    "slack:U123":
      name: Finance Manager
      roles: [manager]
      teams: [finance]
  default_file_policy: deny
```

知识层分为：

- 企业记忆/技能：每个会话都会加载，修改需要审批；
- 团队记忆/技能：按 `governance.users.*.teams` 加载，修改需要审批；
- 用户记忆/技能：保留原来的用户级行为。

详见：

- [docs/admin-onboarding.md](docs/admin-onboarding.md)
- [docs/knowledge-governance.md](docs/knowledge-governance.md)
- [docs/migration-from-hermes.md](docs/migration-from-hermes.md)
- [docs/cron-authorization-panel.md](docs/cron-authorization-panel.md)
- [docs/observability.md](docs/observability.md)

## 许可证

Coorporate Hermes 使用 MIT License。该发行版包含并修改了 Nous Research 以 MIT License 发布的上游 Hermes Agent 组件；相关版权声明已保留在 [LICENSE](LICENSE) 中。
