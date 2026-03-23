# IIIF Stitcher

输入一个 `IIIFViewer` URL，输出该对象下所有页面的大图（默认直下 full 图，失败再回退 tile 拼接）。

## 环境

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m pip install pytest
```

## 运行

```bash
. .venv/bin/activate
iiif-stitcher 'https://digitalarchive.npm.gov.tw/Integrate/IIIFViewer?id=31252&dep=P&imageName=437238^^^19922800088'
```

- 默认输出目录：`./output/<8位hash>/`。  
  例：`./output/a1b2c3d4/001_xxx.jpg`
- 默认启用 `insecure`（关闭 SSL 校验），用于兼容该站点证书链。
- 默认不启用 `tiles`（优先直下 full 图）；可用 `--force-tiles` 强制走切片拼接。
- 已下载文件会做校验后跳过，避免重复下载：  
  会检查文件是否可打开、像素尺寸是否匹配、若服务端提供 `Content-Length` 则还会比对文件大小。
- 如需开启 SSL 校验：加 `--secure`。

## 常用参数样例

```bash
# 指定根输出目录（实际仍会自动加 hash 子目录）
iiif-stitcher -o out 'https://digitalarchive.npm.gov.tw/Integrate/IIIFViewer?id=31252&dep=P&imageName=437238^^^19922800088'

# 强制切片拼接
iiif-stitcher --force-tiles 'https://digitalarchive.npm.gov.tw/Integrate/IIIFViewer?id=31252&dep=P&imageName=437238^^^19922800088'

# 只下载前 5 张
iiif-stitcher --limit 5 'https://digitalarchive.npm.gov.tw/Integrate/IIIFViewer?id=31252&dep=P&imageName=437238^^^19922800088'

# 开启 SSL 校验
iiif-stitcher --secure 'https://digitalarchive.npm.gov.tw/Integrate/IIIFViewer?id=31252&dep=P&imageName=437238^^^19922800088'
```

日志输出到 `./output/<8位hash>/run.log`（或你指定的 `-o` 根目录下对应 hash 子目录）。

## GitHub 发布与下载

已包含 GitHub Actions 工作流：  
[release.yml](/Users/hunter/Workspace/writing_cli/.github/workflows/release.yml)

行为：
- `git tag vX.Y.Z && git push origin vX.Y.Z` 后自动构建并发布 Release 附件
- 手动触发 `workflow_dispatch` 时仅做多平台构建验证（不发布 Release）
- 产物平台：
  - Windows x86_64
  - macOS x86_64
  - macOS arm64
  - Linux x86_64
  - Linux arm64

下载后可直接运行，不需要本地 Python 虚拟环境或 `pip install`。

## 首次推送到 GitHub

```bash
git init
git add .
git commit -m "feat: iiif stitcher cli with resume and release pipeline"
git branch -M main
git remote add origin <你的仓库地址>
git push -u origin main
```

发布二进制：

```bash
git tag v0.1.0
git push origin v0.1.0
```

## 测试（TDD）

```bash
. .venv/bin/activate
pytest -q
```
