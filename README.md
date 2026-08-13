# XiaoR 统一下载中心

本仓库是 XiaoR 软件、设备卡和固件发布的**公开控制中心**，不是二进制
文件仓库。普通 Git 只保存网站、版本清单、更新描述、文档和自动化脚本；
正式发布文件保存在 GitHub Releases，并由 GitHub Actions 增量镜像到
火山引擎 TOS。

## 存储分工

| 内容 | 普通 Git | GitHub Releases | TOS |
| --- | --- | --- | --- |
| APK、EXE、DMG、ZIP、BIN 等发布文件 | 禁止 | 海外源和发布上游 | 国内镜像 |
| `data.json`、`latest.yml`、发布清单 | 保存 | 不作为主入口 | 增量同步 |
| 网站、文档、校验和自动化脚本 | 保存 | 不保存 | 按需增量同步 |

- GitHub Release 单个资产必须小于 2 GiB。
- 超过 2 GiB 的特殊文件标记为 `tos_only`，走单独审批流程。
- 当前版和一个回滚版可以出现在下载中心；删除旧版本必须使用独立维护流程。
- 禁止使用 Git LFS，禁止把发布二进制重新提交到 Git 历史。

## 标准发布流程

### 1. 准备分支

发布人员需要仓库写权限，并使用自己的 GitHub 账号登录 `gh`。本地不需要
配置 TOS AK/SK。

如果一台电脑使用账号隔离包装器，可以通过 `XIAOR_GH` 指定命令，例如：

```bash
export XIAOR_GH=/opt/homebrew/bin/gh-ray
```

```bash
git switch master
git pull --ff-only
git switch -c release/<product>-<version>
```

### 2. 创建 Draft Release 和公开发布清单

```bash
python3 scripts/prepare_release.py \
  --tag xr-controller-v1.4.166 \
  --title "XR Controller v1.4.166" \
  --asset "/absolute/path/app.apk=software/android/app.apk"
```

脚本会完成以下工作：

1. 校验文件类型、文件大小和 TOS 目标路径。
2. 计算 SHA256，不把本机路径写入仓库。
3. 创建或复用 GitHub Draft Release，并上传资产。
4. 生成 `releases/<tag>.json` 公开清单。

多个架构或平台文件可以重复传入 `--asset`。本地文件名必须与 TOS Key 的最后
一段一致；GitHub 不支持的空格或非 ASCII 字符会在 Release 资产名中确定性地
转换，TOS Key 仍保留原名。已经存在但内容不同的 Release 资产不会被覆盖。

### 3. 更新下载中心元数据

根据产品更新 `data.json`、`update/software.yaml` 或对应的 `latest.yml`。
然后执行：

```bash
python3 scripts/validate_release.py
```

XR Studio 同时包含下载中心安装包和 electron-updater 自动更新文件：

- 下载中心安装包发布到 `software/pc/`。
- 自动更新安装包和 `.blockmap` 发布到 `ota/xr-studio/`。
- 带版本号的安装包和 `.blockmap` 只放 GitHub Draft Release，不提交到 Git。
- `ota/xr-studio/latest.yml`、`latest-mac.yml`、图标和 `data.json` 作为小型元数据提交到 Git。
- Action 必须先镜像所有安装包，再镜像 `.blockmap`，验证公开 HTTPS、文件长度和 Range 请求后，才上传 `latest*.yml`；`data.json` 始终最后上传。
- Windows 和 macOS 下载中心文件与 OTA 文件即使内容相同，也使用各自固定的 TOS Key；不得用同步或删除命令代替逐对象增量发布。
- 已发布的版本化对象发现构建错误时不得覆盖原 Key；应使用带纠正标识的新 Key 和新的 Draft Release 清单，再通过审核 PR 更新公开入口。旧对象保留用于审计，但不能继续被入口引用。
- 被替代但保留的对象必须登记在 `releases/audit/superseded-assets.json`，同时声明当前受控发布清单中的替代 Key 和公开原因；校验器会拒绝仍被入口引用、替代对象未被引用或来源不在发布清单中的登记。

### 4. 提交 PR

```bash
git add data.json releases/ update/ software/pc/ firmware/
git commit -m "release: publish <product> <version>"
git push -u origin HEAD
gh pr create --fill
```

- 发布人员使用 `ray-yi-cn` 或其他获授权的协作者账号提交。
- `XiaoRGEEK` 是唯一 PR 审核人，必须批准 PR。
- PR 获得批准后，由 `ray-yi-cn` 或另一名非 `XiaoRGEEK` 的获授权协作者
  执行合并；`XiaoRGEEK` 不执行自己随后需要审批发布的合并。
- 未审核的 Draft Release 不公开，也不会同步到 TOS。

### 5. 合并后的自动发布

受保护的 `master` 合并后，Action 按顺序执行：

1. 校验发布清单和所有引用。
2. 只下载本次新增清单声明的 Draft Release 资产。
3. 复核文件大小和 SHA256。
4. 增量上传到 TOS；同 SHA256 对象跳过，同名不同内容立即失败。
5. 验证 TOS 对象后正式发布 GitHub Release。
6. 最后同步 `data.json`、更新清单和网站，避免提前出现失效链接。

Action 不执行递归全量上传，不覆盖版本化二进制，不自动删除 TOS 对象。
包含新发布清单的运行必须经过 `release-publishing` Environment，唯一审批人是
`XiaoRGEEK`，并启用“禁止触发者自批”。因此标准职责顺序固定为：发布人员
提交、`XiaoRGEEK` 审核、发布人员合并、`XiaoRGEEK` 审批正式发布。不要使用
`XiaoRGEEK` 执行合并，否则该账号会成为部署触发者并被 GitHub 禁止自批。

如果资产发布在元数据更新前失败，不得手工上传或复制清单。修复工作流并通过
PR 审核后，使用受控重放入口明确列出原始清单：

```bash
gh workflow run deploy-tos.yml --ref master \
  -f release_manifests_json='["releases/<tag>.json"]'
```

重放只接受仓库根层的 `releases/<tag>.json`，仍需 `release-publishing`
Environment 审批，并重新执行 Release 资产大小、SHA256、TOS 不覆盖和公开
HTTPS 校验。重放成功后才更新元数据；不得为绕过失败而复制或修改不可变清单。

## 下载源

- GitHub Releases：海外下载源，也是发布流程的上游资产存储。
- TOS 自定义域名：已启用的国内 HTTPS 下载源：
  `https://software.xiao-r.com/`。
- [GitHub Pages](https://xiaorgeek.github.io/DownloadCenterTemplate/)：下载中心网站。

网站下载按钮默认使用国内 HTTPS 源；GitHub Releases 保留为海外下载源和
发布上游。公开页面和元数据不得重新使用 TOS 桶原始域名。

## 开源仓库安全规则

本仓库公开，以下内容**任何时候都不得提交**：

- 火山引擎 AK、SK、STS Token 或 tosutil 配置文件；
- GitHub Token、Cookie、账号配置或认证导出文件；
- SSL 证书私钥、SSH 私钥、签名密钥和密码；
- `.env`、本机绝对路径、个人目录、临时下载目录；
- 包含内部地址、客户数据或未公开产品信息的日志和截图。

工作流只允许引用 GitHub Secrets 的名称，例如
`secrets.TOS_ACCESS_KEY_ID`，Secret 的值只能保存在 GitHub 仓库或受保护
Environment 的设置中。发布脚本只使用 `gh` 当前登录态，不把认证信息写入
文件。

如果怀疑凭据被提交，立即停止发布、吊销并轮换凭据，再清理 Git 历史；不能
只靠新增一次删除提交来处理。

## TOS 维护

- 当前发布和一个回滚发布按产品及架构保留。
- 删除对象是单独、显式审核的维护操作，不属于发布 Action。
- `tos-maintenance` Environment 需要 `XiaoRGEEK` 审批。
- 生命周期规则保留当前对象，非当前版本 30 天后过期，未完成分片 7 天后终止。
