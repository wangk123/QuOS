# material-pool 能力 delta

## ADDED Requirements

### Requirement: 材料上传与解析
平台 SHALL 接受文档(pdf/docx/txt/md)与图片(png/jpg)上传,提取全文文本(parsed_text)入库,原始二进制存文件系统并记录 sha256。
#### Scenario: 上传 PDF 材料
- **WHEN** 用户在材料页上传一份 PDF
- **THEN** 平台解析出全文文本存入 parsed_text,原始文件落盘,sha256 与路径入库,材料出现在列表中
#### Scenario: 上传图片材料
- **WHEN** 用户上传一张 png 图片
- **THEN** 平台按图片材料登记(文本抽取尽力而为,允许 parsed_text 为空),原始文件与 hash 入库

### Requirement: 材料 API 供 agent 消费
平台 SHALL 提供 GET /api/v1/projects/{pid}/materials 返回材料清单含解析文本,作为 agent 加工的输入。
#### Scenario: agent 拉取材料
- **WHEN** agent 调用材料列表接口
- **THEN** 返回该全部材料的 id、文件名、类型、parsed_text

### Requirement: 材料只增不改
材料上传后 SHALL 不支持编辑与覆盖;同 hash 重复上传时提示已存在而非新建。
#### Scenario: 重复上传
- **WHEN** 用户再次上传同 sha256 的文件
- **THEN** 平台提示材料已存在并指向原记录,不产生重复条目
