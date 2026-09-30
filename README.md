# Batch Rename

一个简单好用的 Windows 批量重命名工具。双击 `BatchRename.exe` 即可打开，无需安装 Python。

## 功能

- **批量添加 / 删除前缀**，例如 `IMG_001.jpg` → `旅行_001.jpg`
- **批量添加 / 删除后缀**（扩展名之前），例如 `报告_v1.docx` → `报告_final.docx`
- **删除 / 替换文件名中的任意文字**（“替换为”留空即删除）
- **批量移动到指定文件夹**，可选择是否保留原有子文件夹结构
- **支持子文件夹**：勾选“包含子文件夹”后递归处理所有文件
- **按扩展名筛选**：如只处理 `jpg,png`
- **实时预览**：输入规则时即时显示新旧文件名、位置和状态
- **冲突检测**：重名、目标已存在、非法字符、系统保留名称会被标记并自动跳过
- **撤销**：可逐步撤销本次打开软件后执行过的操作

处理顺序：删除前缀/后缀 → 查找替换 → 添加前缀/后缀。扩展名始终保持不变。

## 获取 exe

### 方法一：从 GitHub Actions 下载（推荐）

每次推送代码后，GitHub 会在 Windows 上自动运行测试并打包（见 `.github/workflows/build-exe.yml`）。
打开仓库的 **Actions** 页面 → 选择最新一次成功的 “Build Windows exe” → 在底部 **Artifacts** 下载 `BatchRename`，
解压后双击 `BatchRename.exe` 即可。

### 方法二：在 Windows 上一键打包

1. 安装 [Python 3.9+](https://www.python.org/downloads/)（安装时勾选 “Add python.exe to PATH”）
2. 双击项目根目录的 `build.bat`
3. 打包完成后会自动打开 `dist` 文件夹，里面的 `BatchRename.exe` 即可双击运行，也可以复制到任何电脑使用

## 从源码运行

```bash
python main.py
```

只依赖 Python 标准库（tkinter）。Linux 上可能需要先安装 `python3-tk`。

## 运行测试

```bash
pip install pytest
python -m pytest -q
```

## 项目结构

```
main.py               程序入口
batch_rename/core.py  扫描、生成重命名计划、冲突检测、执行与撤销（与界面无关）
batch_rename/app.py   tkinter 图形界面
tests/                核心逻辑测试
build.bat             Windows 一键打包脚本
```
