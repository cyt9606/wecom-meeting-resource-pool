# WeCom Meeting Resource Pool

一个面向企业微信的企业微信高级会议资源池。员工从企业微信工作台进入应用，选择时间和预计时长后，系统自动寻找空闲的高级会议账号创建单次会议，并将申请人设为主持人。

> 使用前请自行核对企业微信开放接口、账号许可和组织内部合规要求。

## 功能

- 企业微信 OAuth 身份识别，不接受前端自行声明 userid
- 多个高级会议账号组成资源池，按优先级自动调度
- 查询资源账号已有会议，避免重复占用
- PostgreSQL 原子占位和排斥约束，防止并发超卖
- 创建单次会议并将申请人指定为主持人
- 返回会议 ID、会议号、密码和入会链接
- 查看本人会议、修改主题、取消未开始会议
- 管理后台维护高级资源、管理员和预约策略
- 幂等请求、同源校验、限流、安全响应头和操作审计
- 可选的企业微信客户端 User-Agent 门禁

当前不支持周期会议、固定会议号和普通会议降级。

## 技术栈

- Python 3.10+
- FastAPI / Uvicorn
- PostgreSQL 14+
- Vue 3 / TypeScript / Vite

## 服务架构

```mermaid
flowchart LR
    subgraph client["企业微信客户端"]
        employee["普通员工"]
        admin["管理员"]
        spa["Vue 3 单页应用"]
        employee -->|"申请、查看、修改、取消"| spa
        admin -->|"资源、管理员、策略配置"| spa
    end

    subgraph service["会议资源池服务 · FastAPI / Uvicorn"]
        static["静态文件服务<br/>app/static"]
        guard["访问控制与安全中间件<br/>企业微信客户端门禁 · Session · 安全响应头"]
        auth["OAuth 路由<br/>/auth/*"]
        api["业务 API<br/>/api/v1/*<br/>身份鉴权 · 同源校验 · 限流 · 审计"]
        scheduler["资源调度器<br/>策略校验 · 幂等 · 远端忙闲检查<br/>资源选择 · 主持人校验 · 失败回滚"]
        repository["Repository<br/>原子占位 · 状态写入 · 管理配置"]
        wecom_client["WeComClient<br/>access_token 缓存 · 失效重试 · 错误归一化"]
        startup["应用启动生命周期<br/>初始化表结构 · 同步初始资源/管理员<br/>释放过期临时占位"]

        static -.->|"提供页面"| spa
        guard --> auth
        guard --> api
        api --> scheduler
        api --> repository
        scheduler --> repository
        scheduler --> wecom_client
        auth --> wecom_client
        startup --> repository
    end

    subgraph data["PostgreSQL"]
        db[("meeting_resource<br/>reservation<br/>resource_calendar_slot<br/>app_admin · system_policy<br/>operation_log")]
    end

    subgraph wecom["企业微信开放平台"]
        oauth_api["OAuth 与成员身份接口"]
        meeting_api["会议查询、创建、详情<br/>修改、取消接口"]
        message_api["应用消息接口"]
    end

    spa -->|"HTTPS / JSON"| guard
    repository -->|"事务、排斥约束"| db
    wecom_client --> oauth_api
    wecom_client --> meeting_api
    wecom_client --> message_api
```

核心数据流为：工作台身份进入 → 服务端 OAuth 确认 `userid` → 校验预约策略 →
逐个检查高级资源的远端会议 → PostgreSQL 原子占位 → 创建会议并校验申请人为主持人 →
确认占位并返回会议号、密码和入会链接。管理员配置直接存储在数据库中，修改后即时生效。

## 快速开始

### 1. 创建数据库

```bash
createdb wecom_meeting_pool
```

应用启动时会自动执行 `app/schema.sql`。

### 2. 配置后端

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
cp .env.example .env
```

Windows PowerShell 激活命令：

```powershell
.\.venv\Scripts\Activate.ps1
```

编辑 `.env`，至少填写：

- `APP_BASE_URL`：自建应用的可信访问地址
- `SESSION_SECRET`：至少 32 个随机字符
- `DATABASE_URL`：PostgreSQL 连接串
- `WECOM_CORP_ID`：企业 CorpID
- `WECOM_APP_SECRET`：自建应用 Secret
- `WECOM_AGENT_ID`：自建应用 AgentId
- `WECOM_MEETING_RESOURCE_USERIDS`：持有高级会议权限的 userid，逗号分隔
- `WECOM_ADMIN_USERIDS`：首次启动时引导的管理员 userid

生产环境建议把 Secret 放入权限受控的独立环境文件或 Secret Manager，不要提交到 Git。

本仓库只包含会议资源池核心应用，不包含反向代理、TLS 证书、域名认证文件或其他
特定服务器的基础设施配置。

### 3. 构建前端

```bash
cd frontend
pnpm install
pnpm test
pnpm build
cd ..
```

Vite 会把生产文件输出到 `app/static`。

### 4. 启动

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

健康检查：

```bash
curl http://127.0.0.1:8001/health
```

## 企业微信配置

1. 创建企业微信自建应用并设置应用主页。
2. 将 `APP_BASE_URL` 对应域名配置为可信域名；按企业微信后台提示下载认证文件，并由
   实际托管环境将该文件发布到域名根路径。认证文件可能包含组织专属校验值，不要提交
   到公开仓库。
3. 为应用配置可见范围。
4. 按企业微信后台要求开通通讯录成员读取以及会议创建、查询、修改、取消等接口权限。
5. 将高级会议许可持有人的 userid 加入资源池。

不同企业微信版本和许可下可用接口可能不同，请以企业微信管理后台和官方接口响应为准。

## 服务状态转移

### 预约状态

```mermaid
stateDiagram-v2
    direction LR

    [*] --> HELD: 策略校验通过并原子占位
    HELD --> CREATING: 开始调用创建会议接口
    HELD --> FAILED: 启动清理发现两分钟临时占位已过期

    CREATING --> CREATED: 创建成功且主持人校验通过
    CREATING --> FAILED: 创建接口失败
    CREATING --> FAILED: 详情或主持人校验失败，尝试取消远端会议

    CREATED --> UPDATING: 修改未开始会议的主题
    UPDATING --> CREATED: 修改成功
    UPDATING --> CREATED: 修改失败，记录错误并恢复

    CREATED --> CANCELLING: 取消未开始的会议
    CANCELLING --> CANCELLED: 远端取消成功或会议已取消
    CANCELLING --> RECONCILING: 远端取消结果不确定

    FAILED --> [*]
    CANCELLED --> [*]

    note right of CREATED
        会议自然结束不会触发本地状态迁移，
        历史记录仍保留为 CREATED。
    end note

    note right of RECONCILING
        保留 ACTIVE 资源占位，防止不确定结果下重复分配。
        当前版本需人工或后续任务核对。
    end note
```

`FAILED` 和 `CANCELLED` 是终止状态；`RECONCILING` 表示远端结果不确定，并非取消成功。
幂等键命中已有预约时直接返回原记录，不创建新的状态实例。

### 资源时段占位状态

```mermaid
stateDiagram-v2
    direction LR

    state "HELD" as SLOT_HELD
    state "ACTIVE" as SLOT_ACTIVE
    state "RELEASED" as SLOT_RELEASED

    [*] --> SLOT_HELD: 创建预约与临时占位
    SLOT_HELD --> SLOT_ACTIVE: 预约确认 CREATED
    SLOT_HELD --> SLOT_RELEASED: 创建失败或临时占位过期
    SLOT_ACTIVE --> SLOT_RELEASED: 预约确认 CANCELLED
    SLOT_RELEASED --> [*]

    note right of SLOT_ACTIVE
        PostgreSQL 排斥约束禁止同一资源的
        HELD 或 ACTIVE 时段发生重叠。
    end note
```

预约与资源占位在同一业务流程中联动：预约 `HELD → CREATING → CREATED` 对应资源占位
`HELD → ACTIVE`；创建失败对应资源占位 `HELD → RELEASED`；取消结果不确定时预约进入
`RECONCILING`，资源占位保持 `ACTIVE`。

### 高级资源可用状态

```mermaid
stateDiagram-v2
    direction LR

    [*] --> HEALTHY: 新增或启用资源
    HEALTHY --> DISABLED: 管理员停用
    DISABLED --> HEALTHY: 管理员重新启用

    state "DEGRADED（数据库预留，当前无自动迁移）" as DEGRADED
```

## 测试

```bash
pytest -q

cd frontend
pnpm test
pnpm build
```

生产接口联调脚本位于 `tools/`。运行端到端脚本会真实创建并立即取消一场测试会议，
请仅在隔离时段和明确授权下使用。

## 安全说明

- `.env*` 默认被忽略，仅 `.env.example` 可以提交。
- OAuth 会话使用服务端签名 Cookie；生产环境应使用 HTTPS。
- 管理员权限从数据库即时读取，并强制至少保留一名管理员。
- 资源只停用、不物理删除，以保留历史预约和审计记录。
- `REQUIRE_WECOM_CLIENT=true` 会拒绝不含 `wxwork` 标识的请求，但 User-Agent 可伪造，
  不能代替 OAuth 和权限校验。

详见 [SECURITY.md](SECURITY.md)。

## License

[MIT](LICENSE)
