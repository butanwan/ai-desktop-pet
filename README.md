# 通用桌面宠物 · Universal Desktop Pet

一个运行在 Windows 上的轻量桌面宠物（桌宠）。角色是透明 PNG 帧动画，可以拖拽、点击互动、显示随机气泡，内置离线小游戏、天气状态、鼠标交互，并支持接入本地大模型（Ollama / OpenAI 兼容接口）进行聊天。

> 项目目录名：`silver_moon_pet`（GitHub 仓库：`butanwan/ai-desktop-pet`）。

---

## 功能特性

- **桌宠本体**：透明 PNG 帧动画，常驻桌面，可拖拽、置顶、缩放、调透明度。
- **角色系统**：内置角色包，导入自定义角色时**自动识别帧并生成鼠标点击范围**（bboxes），无需手动抠像。
- **自动气泡**：随机/闲置时冒出可爱台词，显示时会自动把 `{pet_name}` 及旧角色名替换为当前设置的名字。
- **互动**：点击抚摸、双击放大、鼠标移入移出表情切换、临边贴靠、拽飞松开回弹。
- **内置小游戏**：2048、推箱子、贪吃蛇、石头剪刀布、扫雷、俄罗斯方块、五子棋（共 7 款）。
- **状态系统**：心情 / 饥饿 / 精力 / 好感度，可抚摸、喂食、打工、购物、睡觉；支持天气联动。
- **聊天（可选）**：接入 Ollama 或 OpenAI 兼容 API，角色拥有可自定义的长期记忆与人设。
- **角色独立记忆**：每个角色使用独立的记忆文件（如 `chat_memory_苏璃.json`），切换角色记忆不会串台。
- **默认人设**：内置「苏璃」「银月」两套默认人设，可在设置里一键恢复，也可自行改写为任意角色。
- **桌宠设置**：图形化设置界面，可改角色、角色名、人设、配色、模型、天气城市、开机自启等。
- **即时切换**：在设置里改好角色 / 名字 / 配色后，点“启动桌宠”即可**即时生效**，无需反复退出重开。

> ⚠️ **人设（角色设定）中的角色名保持原样**，程序不会自动替换。气泡、托盘、菜单等界面文案会自动跟随设置的名字；但人设文本如需改名，请在设置里手动编辑。

---

## 目录结构

```
silver_moon_pet/
├─ main.py              # 桌宠主程序（帧动画 / 互动 / 气泡 / 托盘 / 热重载）
├─ settings_tool.py     # 桌宠设置界面
├─ launcher.py          # 启动器（启动桌宠 / 自定义设置 / 说明）
├─ chat.py              # 聊天与记忆（Ollama / OpenAI 兼容）
├─ character.py         # 角色包发现与路径管理
├─ games.py             # 内置小游戏（2048 / 推箱子 / 贪吃蛇 / 猜拳 / 扫雷 / 俄罗斯方块 / 五子棋）
├─ status.py            # 状态系统（心情/饥饿/精力/好感度/天气/打工）
├─ theme.py             # 配色主题
├─ bbox_utils.py        # 角色范围（包围盒）计算（导入角色时自动生成 bboxes）
├─ run_pet.py           # 轻量启动器（无控制台，打包用）
├─ run_settings.py      # 轻量设置启动器（无控制台，打包用）
├─ persona.txt          # 当前角色人设（可在设置中编辑，已 gitignore）
├─ icon.ico             # 程序图标
├─ install_deps.bat     # 首次依赖安装脚本
├─ .gitignore           # 忽略运行时配置 / 记忆 / 缓存等私有文件
├─ .gitattributes       # Git LFS 规则（角色包大文件走 LFS）
├─ LICENSE
├─ characters/          # 角色包目录（每个子目录一个角色，走 Git LFS）
│  ├─ 苏璃/
│  ├─ 银月/
│  └─ ...
├─ config.json          # 运行时配置（自动生成，已 gitignore）
├─ status.json          # 运行时状态（自动生成，已 gitignore）
└─ chat_memory_*.json   # 各角色的独立聊天记忆（自动生成，已 gitignore）
```

> ℹ️ 角色范围（鼠标点击范围 `bboxes.json`）在导入角色包时由 `bbox_utils.py` 自动计算，无需手动抠像。

---

## 快速开始

### 方式一：直接运行打包好的 exe（已打包环境）

1. 双击 `install_deps.bat `首次会自动创建 venv 并安装 PySide6 / numpy / Pillow
2. 双击 `启动桌宠.exe` 启动桌宠。
3. 双击 `桌宠设置.exe` 打开设置。
4. 在设置中可切换角色、修改角色名、调整配色、配置模型与天气，点“启动桌宠”即时生效。

### 方式二：源码运行

需要 **Python 3.10+**。

```bash
# 1. 安装依赖（首次会自动创建 venv 并安装 PySide6 / numpy / Pillow）
install_deps.bat

# 2. 启动桌宠
python main.py

# 3. 打开设置
python settings_tool.py
```

依赖清单（也可手动 `pip install`）：

```
PySide6 numpy Pillow
```

---

## 角色包格式

把角色包放到 `characters/<角色名>/` 下：

```
characters/<角色名>/
├─ frames/              # 常驻动画帧（*.png，透明背景）
│  ├─ 0001.png
│  ├─ 0002.png
│  └─ ...
├─ bboxes.json          # 鼠标点击范围（自动生成，可手动改）
└─ character.json       # 角色元数据（可选）
```

- **导入自定义角色**：在桌宠设置 → “导入角色包” 选择包含 PNG 的文件夹。工具会自动：
  - 把散落的 PNG 归到 `frames/`；
  - 自动识别帧，计算不透明像素包围盒，生成 `bboxes.json`（角色范围）；
  - 在 `config.json` 记录角色，点“启动桌宠”即时切换。
- `bboxes.json` 字段：`human`（点击范围 `[x,y,w,h]`，基于 240×320 画布坐标系）、`size`、`clickable`。
- 默认内置角色（无角色包）显示名为“苏璃”，可在设置中修改角色名为任意名称。**界面文案**（气泡 / 托盘 / 菜单）会同步生效；**人设文本**保持原样，如需改名请在“角色设定”里手动编辑。

---

## 配置说明（config.json）

主要字段：

| 字段 | 说明 |
|------|------|
| `pet_name` | 角色显示名，全局生效 |
| `character_id` | 当前角色包目录名 |
| `scale` | 缩放比例 |
| `opacity` | 窗口透明度 |
| `topmost` | 是否置顶 |
| `theme` | 配色（`name` + `colors`） |
| `model_provider` | 聊天模型供应商：`ollama` / `openai` |
| `ollama_url` / `api_base` | 模型服务地址 |
| `model` | 模型名 |
| `api_key` | API Key（OpenAI 兼容） |
| `weather_city` / `weather_enabled` | 天气城市与开关 |
| `autostart` | 开机自启 |
| `x` / `y` | 窗口位置 |

---

## 聊天 / AI 配置

在“桌宠设置 → 模型与聊天”中：

- **Ollama（默认）**：本地安装 Ollama，拉取模型（如 `qwen2.5`），地址填 `http://127.0.0.1:11434`。
- **OpenAI 兼容**：填 `api_base`（如 `https://api.openai.com/v1/chat/completions`）、`model`、`api_key`。
- 人设（`persona.txt`）可在设置中自由编辑，**内容保持原样**，程序不会自动替换其中的角色名。
- 内置两套默认人设，可在“角色设定”里一键“恢复苏璃默认”或“恢复银月默认”（苏璃为青丘九尾狐妖，银月为《凡人修仙传》月华仙子 / 银月狼族），也可自行改为其他角色。

### 角色独立记忆

每个角色拥有独立的记忆文件，位于程序目录下：

| 角色 | 记忆文件 |
|------|----------|
| 苏璃（默认） | `chat_memory_苏璃.json` |
| 银月 | `chat_memory_银月.json` |
| 其他角色 | `chat_memory_<角色ID>.json` |

- 切换角色时会自动切换到对应角色的记忆文件，**不会串台**。
- 想清空某个角色的记忆：在聊天窗口点“清空”，或直接删除对应文件。
- 首次从旧版本升级时，旧版单一的 `chat_memory.json` 只会被迁移给默认角色一次，新角色从空白开始。

> 未配置模型时，桌宠仍可正常使用（气泡、互动、小游戏、状态系统均离线可用）。

---

## 打包（提供给维护者）

使用 PyInstaller 等工具将上述脚本分别打包为 `启动桌宠.exe` 与 `桌宠设置.exe`，并配套 `run_pet.py` / `run_settings.py` 作为无控制台启动器。打包时把 `characters/`、`persona.txt`、`icon.ico`、`config.json` 等一并带入同目录。

---

## 开发 / 仓库说明

### 角色包使用 Git LFS

`characters/` 下的 PNG / MP4 体积较大，仓库使用 **Git LFS** 管理（规则见 `.gitattributes`）。

克隆仓库前请先安装 [Git LFS](https://git-lfs.com)，否则拉下来的角色包只会是几十字节的指针文件、无法正常显示：

```bash
git lfs install
git clone https://github.com/butanwan/ai-desktop-pet.git
```

已经克隆过的仓库，补拉 LFS 文件：

```bash
git lfs pull
```

新增角色资源时，确认 LFS 已接管：

```bash
git lfs track "characters/**"
git add .gitattributes
git add characters/
git commit -m "添加角色资源"
git push origin main
```

> GitHub LFS 免费额度为 1GB 存储 + 1GB/月 下载流量，超出会产生费用。若不想上传角色包，可在 `.gitignore` 中取消 `characters/` 一行的注释，改为用网盘分发资源。

### 提交前注意

以下文件已在 `.gitignore` 中排除，**不要提交**（属于个人数据与运行时生成物）：

- `config.json` — 个人配置（角色 / 名字 / 模型 / API Key 等）
- `persona.txt` — 当前人设
- `status.json` — 养成状态存档
- `chat_memory_*.json` — 各角色聊天记忆（可能含隐私对话）
- `__pycache__/`、`build/`、`dist/` — 缓存与打包产物

### 依赖

```
PySide6 numpy Pillow
```

---

## 许可证

详见 [LICENSE](LICENSE)。
