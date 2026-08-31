# 通用桌面宠物 · Universal Desktop Pet

一个运行在 Windows 上的轻量桌面宠物（桌宠）。角色是透明 PNG 帧动画，可以拖拽、点击互动、显示随机气泡，内置离线小游戏、天气状态、鼠标交互，并支持接入本地大模型（Ollama / OpenAI 兼容接口）进行聊天。

> 项目目录名：`AIPet`。

---

## 功能特性

- **桌宠本体**：透明 PNG 帧动画，常驻桌面，可拖拽、置顶、缩放、调透明度。
- **角色系统**：内置角色包，导入自定义角色时**自动识别帧并生成鼠标点击范围**（bboxes），无需手动抠像。
- **自动气泡**：随机/闲置时冒出可爱台词，台词中的角色名随设置实时替换。
- **互动**：点击抚摸、双击放大、鼠标移入移出表情切换、临边贴靠、拽飞松开回弹。
- **内置小游戏**：猜数字、石头剪刀布、21 点等（文本交互）。
- **状态系统**：心情 / 精力 / 好感度，可喂食、查看状态；支持天气联动。
- **聊天（可选）**：接入 Ollama 或 OpenAI 兼容 API，角色拥有可自定义的长期记忆与人设。
- **桌宠设置**：图形化设置界面，可改角色、角色名、配色、模型、天气城市、开机自启等。
- **即时切换**：在设置里改好角色 / 名字 / 配色后，点“启动桌宠”即可**即时生效**，无需反复退出重开。

---

## 目录结构

```
AIPet/
├─ main.py              # 桌宠主程序（帧动画 / 互动 / 气泡 / 托盘 / 热重载）
├─ settings_tool.py     # 桌宠设置界面
├─ launcher.py          # 启动器（启动桌宠 / 自定义设置 / 说明）
├─ chat.py              # 聊天与记忆（Ollama / OpenAI 兼容）
├─ character.py         # 角色包发现与路径管理
├─ games.py             # 内置小游戏
├─ status.py            # 状态系统（心情/精力/好感度/天气）
├─ theme.py             # 配色主题
├─ bbox_utils.py        # 角色范围（包围盒）计算（导入角色时自动生成 bboxes）
├─ run_pet.py           # 轻量启动器（无控制台，打包用）
├─ run_settings.py      # 轻量设置启动器（无控制台，打包用）
├─ persona.txt          # 默认角色人设（可在设置中编辑）
├─ icon.ico             # 程序图标
├─ install_deps.bat     # 首次依赖安装脚本
├─ LICENSE
├─ characters/          # 角色包目录（每个子目录一个角色）
│  ├─ 苏璃/
│  ├─ 银月/
│  └─ ...
├─ config.json          # 运行时配置（自动生成，已 gitignore）
└─ status.json          # 运行时状态（自动生成，已 gitignore）
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
- 默认内置角色（无角色包）显示名为“苏璃”，可在设置中修改角色名为任意名称，全局（气泡 / 托盘 / 聊天人设）同步生效。

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
- 人设（`persona.txt`）可在设置中编辑，角色名会按当前 `pet_name` 自动替换。
- 内置两套默认人设，可在“角色设定”里一键“恢复苏璃默认”或“恢复银月默认”（苏璃为青丘九尾狐妖，银月为《凡人修仙传》月华仙子 / 银月狼族），也可自行改为其他角色。

> 未配置模型时，桌宠仍可正常使用（气泡、互动、小游戏、状态系统均离线可用）。

---

## 打包（提供给维护者）

使用 PyInstaller 等工具将上述脚本分别打包为 `启动桌宠.exe` 与 `桌宠设置.exe`，并配套 `run_pet.py` / `run_settings.py` 作为无控制台启动器。打包时把 `characters/`、`persona.txt`、`icon.ico`、`config.json` 等一并带入同目录。

---

## 许可证

详见 [LICENSE](LICENSE)。
