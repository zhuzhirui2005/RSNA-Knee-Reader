# RSNA Knee Reader

[English](README.md)

让支持MCP和图像输入的客户端直接浏览服务器上的膝关节MRI：读取报告、获取全部序列、连续翻阅切片，并按需查看原分辨率细节。

工具来自RSNA Knee Abnormality Detection竞赛项目，完整方案获得 **Private AUC 0.955、Rank 21、Solo Gold**。这里开源的是阅片基础设施，不包含竞赛训练模型，也不会自行诊断。

## 保留的功能

- `list_cases`：分页列出病例编号。
- `get_case`：返回报告、序列列表、图像尺寸及方向信息。
- `read_slices`：每次最多4张JPEG预览，或1张原分辨率PNG细节图。
- 根据DICOM几何位置排序，支持窗宽窗位、整序列一致的自动窗和原图坐标裁剪。
- 从普通DICOM文件或逐病例无损存档读取，无需每次解压整个病例。
- 标准stdio和Streamable HTTP连接，合成病例示例与自动化测试。

仓库不包含真实病例、报告、gold答案、模型权重、账号凭据或原项目专用隧道。读取服务本身无需GPU或付费API；模型由连接它的客户端提供。

## 五分钟试用

需要Python 3.11及以上：

```sh
git clone https://github.com/zhuzhirui2005/rsna-knee-reader.git
cd rsna-knee-reader
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell改用：.venv\Scripts\Activate.ps1
python -m pip install -e .
rsna-knee-reader demo .demo
rsna-knee-reader serve --catalog .demo/catalog.json --data-root .demo/dicom
```

最后一步启动stdio MCP服务，等待客户端连接，不会显示阅片网页。示例生成两个仅含移动几何图形的合成病例，不需要下载竞赛数据。[客户端配置示例](examples/mcp-client.json)使用绝对路径，避免受客户端工作目录影响。

使用HTTP时：

```sh
rsna-knee-reader serve --catalog .demo/catalog.json --data-root .demo/dicom --transport http
```

MCP地址是`http://127.0.0.1:8768/mcp`，健康检查地址为`/healthz`。远程托管、认证及Docker说明见[部署文档](docs/deployment.md)。

## 导入自己的病例

将已获使用许可并完成去标识处理的单帧灰度MR文件放入数据目录，扩展名使用`.dcm`。目录结构不限，索引按DICOM中的检查、序列UID分组，并优先按几何位置排列切片。

报告可选，使用UTF-8 JSON将`StudyInstanceUID`映射到报告字符串：

```sh
rsna-knee-reader index --data-root data/dicom --reports data/reports.json --output data/catalog.json
rsna-knee-reader serve --catalog data/catalog.json --data-root data/dicom
```

不提供`--reports`即可只读取影像。重新索引时保留既有病例编号和已归档病例，服务会在目录索引更新后重新加载。修改同一路径的影像内容后应重启服务，以清除像素缓存。索引操作不会自动去除DICOM或报告里的身份信息。

当前版本支持经典单帧灰度MRI；增强型多帧DICOM需要专门处理逐帧几何信息，尚未支持。JPEG等压缩传输语法可额外安装`python -m pip install -e ".[compressed]"`。更多格式说明见[目录格式](docs/catalog-format.md)。

## 连续阅片约定

先调用`get_case`，再按序列从`start=1`、`count=4`开始读取，始终按返回的`next_start`翻页，直到为null。传入大于页上限的count只会截为当前页，不会跳过切片。

预览单张影像内容最长边最多512像素，方向和编号边框另计；四张拼图整体可以超过512像素。细节读取使用`detail="native"`、`layout="individual"`、`count=1`。这里的原分辨率指空间尺寸不缩放，PNG仍经过8位显示窗处理，不是原始DICOM强度数组。

`crop=[x,y,width,height]`使用原图坐标，不能使用预览或拼图坐标。窗宽窗位必须同时设置；`window="auto"`使用整序列一致的百分位显示窗。方向标记表示占主导的患者方向，服务不会旋转图像。

病例内部串行翻页，不同病例可以分配给独立代理并行处理。可参考[中文标注提示词](prompts/knee-annotation.zh-CN.md)和[概率输出规范](examples/probability-output.schema.json)。标注结果由客户端生成，服务不包含参考标签，也不负责保存诊断。

## 无损存储

```sh
rsna-knee-reader archive --catalog data/catalog.json --data-root data/dicom --archives data/archives
rsna-knee-reader serve --catalog data/catalog.json --data-root data/dicom --archives data/archives
```

`.dcmz`保留完整DICOM原始字节，逐文件进行可逆变换和Zstandard压缩；服务可以直接读取其中单张影像。压缩命令会验证字节往返一致，不会删除原文件或覆盖已有存档。若原文件不存在，读取服务自动查找存档。

恢复原文件：

```sh
rsna-knee-reader restore --archives data/archives --study-uid 检查UID --destination data/restored
```

此格式是工具自用的存档格式，不是标准DICOM传输语法。原始文件的字节无损与显示用JPEG/PNG是两个不同概念。

## 开发与许可

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m build
```

测试全部使用合成数据，覆盖几何排序、连续分页、裁剪、显示窗、存档恢复、MCP调用和HTTP认证。新实现使用官方MCP SDK v2处理现代及旧版协议，原服务的账号专用隧道和协议补丁不再作为依赖。

代码采用[MIT许可](LICENSE)，来源边界见[provenance](docs/provenance.md)。数据使用许可与代码许可分开；原始DICOM留在服务器，但请求的图像和报告会传给连接的模型客户端。本工具用于研究，未作为临床诊断设备验证。
