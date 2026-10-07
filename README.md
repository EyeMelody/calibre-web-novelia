# Calibre-Web Novelia 元数据插件 🧩

为 Calibre-Web / Calibre-Web Automated（CWA）提供[轻小说机翻网（Novelia）](https://n.novelia.cc/)元数据检索。当前版本：**1.3.1**。

## ✨ 功能

- 支持中文、日文书名及部分标题检索。
- 同时检索 Web 小说与文库作品；配置有相应权限的访问令牌后支持 R18。
- 同一作品提供**中文翻译版**和**原文版**两组元数据候选。
- 支持标题、简介、作者、标签、作品链接及 Novelia 标识符。
- 保留作品链接和作品 ID 检索方式。
- 提供器名称为 `Novelia`；结果来源分别标注 `Novelia · 中文翻译版` 与 `Novelia · 原文版`，不会给书名添加区分后缀。

Web 来源包括 Kakuyomu、成为小说家吧、Novelup、Hameln、Pixiv、Alphapolis。只检索 Novelia 已收录的作品，不直接搜索这些原作网站。

## 🏗️ 安装

### Calibre-Web

将 [`novelia.py`](./novelia.py) 复制到项目的 `cps/metadata_provider/` 目录，然后重启服务。它是 Calibre-Web 元数据提供器，不应安装到 Calibre 引擎的插件目录。

### CWA / Docker Compose

将文件放到 Compose 项目下的 `./calibre/plugins/folder/calibre-web-novelia/novelia.py`，向现有服务合并以下配置：

```yaml
services:
  calibre-web-automated:
    environment:
      - NOVELIA_ACCESS_TOKEN=${NOVELIA_ACCESS_TOKEN:-}
    volumes:
      - ./calibre/plugins/folder/calibre-web-novelia/novelia.py:/app/calibre-web-automated/cps/metadata_provider/novelia.py:ro
```

这只是需要合并的配置片段，请保留原有镜像、端口、书库及其他挂载。先放好真正的 Python 文件，再应用配置并**重新创建容器**。仅重启旧容器不能应用新增环境变量或挂载。

在 CWA 元数据提供器设置中启用 `Novelia`。若未出现，检查容器日志和插件挂载路径；不同版本的容器布局可能有差异。

## 🔨 环境变量

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `NOVELIA_ACCESS_TOKEN` | Novelia 访问令牌；有权限的账号可检索 R18 | 空，使用公开检索 |
| `NOVELIA_BASE_URL` | API 来源，仅支持 `https://n.novelia.cc` 或 `https://n.novelia.top` | `https://n.novelia.cc` |
| `HTTP_PROXY` / `HTTPS_PROXY` | requests 使用的代理地址 | 未设置 |
| `NO_PROXY` | 不经过代理的主机 | 未设置 |

在 Compose 项目同目录的 `.env` 中填写：

```dotenv
NOVELIA_ACCESS_TOKEN=你的访问令牌
```

也可以直接在服务的 `environment:` 中赋值。普通 Docker 网络中的 `127.0.0.1` 指容器自身，代理应使用 NAS 可达的地址。

### 获取访问令牌

1. 在 Novelia 登录自己的账号，并确认该账号能访问目标分类。
2. 打开浏览器开发者工具的 **Network → Fetch/XHR**，在站内执行搜索。
3. 选择发往 `/api/novel` 或 `/api/wenku` 的请求，在 **Request Headers** 中找到 `Authorization: Bearer ...`。
4. 复制访问令牌到 `NOVELIA_ACCESS_TOKEN`，重新创建容器。

支持纯令牌或带 `Bearer ` 前缀的值，不包含 `Authorization:`。不自动登录或续期，令牌过期后需要更新环境变量并重新创建容器。不要提交真实令牌或 `.env` 文件。

该变量由服务器共用，不是每位 CWA 用户单独登录。未配置时检索一般向 Web 和普通文库轻小说；配置有效令牌后，两类检索均使用全部分类，访问范围由站点账号权限决定。

**从旧版升级：**1.3.0 只支持 `NOVELIA_ACCESS_TOKEN`，不再读取 `NOVELIA_TOKEN` 或 `NOVELIA_TOKEN_FILE`。替换插件、移除旧变量及本插件专用的令牌文件挂载配置，再重新创建容器即可，无须删除书籍或数据库。

## 📖 使用

在书籍编辑页面打开“获取元数据”，输入书名并搜索，例如：

```text
腐血的萨尔
腐血のサルヴァトーレ
狼与香辛料
狼と香辛料
```

也接受作品链接、`novelia:hameln/306520`、`hameln/306520` 或 `novelia:wenku/6450c43284972153850fa818`。

每类最多检索 5 部作品，每部最多返回两组候选，合计最多 20 个。Web 按相关度排列，文库保留站点返回顺序。中文候选在原文候选之前，两组使用不同结果 ID，但共享同一作品标识符。

### 双版本与字段

| 字段 | 中文翻译版 | 原文版 |
| --- | --- | --- |
| 书名 | 站点中文标题 | 原文标题 |
| 简介 | 站点中文简介 | 原文简介 |
| 作者、关键词 | 保留接口原值 | 保留接口原值 |

缺少中文标题时只返回原文候选；缺少相应语言简介时不混用另一种语言。本插件不额外翻译作者或关键词。文库通常只有一份站点简介，没有独立日文简介字段，因此原文候选可提供日文标题，但无法提供站点未提供的日文简介。

### 标签与描述

- 两组候选均固定添加 `机翻`、`轻小说机翻网`。
- Web 添加 `WEB版`，文库添加 `文库版`。
- 原作状态直接使用 `已完结`、`连载中` 等标签，不加字段名前缀。
- 保留站点关键词和注意事项，可能包含日文；标签去重，最多 60 个，固定标签优先保留。
- 描述仅包含所选语言的作品简介，不附加类型、元数据来源、原文标题、原作状态、作品页面或插画信息。作品链接和标识符仍保留在各自字段中；缺少相应语言简介时，描述为空。

`机翻` 是此插件的固定分类标签，原文候选同样带有该标签；它不表示原文文本经过了翻译。

## ⚠️ 使用范围与排错

- Web 返回作品级信息，文库返回系列级信息。不会猜测本地文件的卷号、丛书序号、译者、语言或出版日期，也不替换封面。
- 应用前请核对卷号、简介和现有标签。CWA 可能替换整个字段，来源及译者标签按需合并。
- `已完结` 指原作状态，不代表译文或本地 EPUB 收全。
- 插件只提供候选，不直接写书库或 EPUB。文件元数据写回由 CWA 的设置和后台任务负责。
- HTTP 401/403：检查访问令牌是否过期、账号权限和环境变量是否生效。
- 搜不到：尝试更短的关键字或日文原名；站点未收录的译名和繁简体别名不保证匹配。
- 请求失败：检查 NAS 网络与代理。插件不跟随重定向，也不自动重试限流请求。
- 作品详情缓存 5 分钟，搜索候选列表每次重新获取。

## 🧪 测试

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

仓库测试使用独立的 CWA 数据类替身，检查认证、双候选、标签、缺失字段与搜索结果映射。另已使用实际 CWA 数据类及公开 API 验证 Web、文库中日文书名检索；没有用户访问令牌，未验证实际 R18 授权检索。尚未对各版本 CWA 做完整网页端兼容测试。

## 🙏 鸣谢

特别感谢 [JeffersonQin/calibre-web-bgm](https://github.com/JeffersonQin/calibre-web-bgm)，该项目为本插件提供了 Calibre-Web 元数据提供器的实现思路参考，本 README 的组织方式也参考了该项目。

同时感谢 [Novelia / auto-novel](https://github.com/auto-novel/auto-novel) 提供作品信息与接口，以及 [Calibre-Web Automated](https://github.com/crocodilestick/Calibre-Web-Automated) 提供元数据扩展机制。
