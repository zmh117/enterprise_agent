## 1. 收回开放测试重置范围

- [ ] 1.1 从`open_test_reset.py`删除当前Agent/Application合同常量、legacy contract inventory、Publication snapshot/hash判断、跨域delete/update helper及其结果字段
- [ ] 1.2 删除reset对Agent Definition/Publication、Business Application Revision/Publication、Route、Deployment、Tool/Skill/Channel/Webhook绑定的修改，保留文件域根、强关联终态事实、非终态门禁和双对象命名空间清理
- [ ] 1.3 删除遗留配置级联删除测试及其Agent/Application数据构造，增加公开`report/apply`行为测试证明reset不修改配置域事实
- [ ] 1.4 确认migration 119仍会对遗留Runtime/Profile/Publication引用失败关闭，且本变更不新增migration、回填或配置清理命令

## 2. 删除单实现抽象与未来扩展点

- [ ] 2.1 将`SchemaHeadValidator`的previous-head接口从集合参数收窄为单个明确前序head，并让reset CLI只声明`118`
- [ ] 2.2 删除`TextFormatPolicy`、`CURRENT_TEXT_FORMAT_POLICY`和`get_text_format_policy()`，以固定文本格式tuple及按code/名称函数更新所有生产调用方
- [ ] 2.3 删除单元素`PROFILE_REGISTRY`及遍历，直接解析`NONE`或`DOCLING_LAYOUT_OCR_V2`并直接校验当前Profile hash
- [ ] 2.4 保留`TextFormatDefinition`、`DocumentProcessingProfile`、`DoclingServeProvider`、对象存储Protocol和reset service/CLI边界，防止把必要领域值与基础设施边界误删

## 3. 删除恒真、不可达和无调用方代码

- [ ] 3.1 删除readiness `core.runtime_assembly`恒真字段及后端测试断言，不增加兼容alias或替代占位
- [ ] 3.2 删除`file_format_policy_unknown`错误目录项和不可达的`file_format_policy_denied`分支，确认生产代码无剩余引用
- [ ] 3.3 删除`file_get_metadata`目录候选二次查询、`_is_frozen_catalog_candidate`和`file_catalog_candidate_requires_materialization`错误码，恢复既有Manifest拒绝边界
- [ ] 3.4 删除前端运行记录测试输入中的`policy_source`残留，以及通过错误Python函数签名验证版本选择器已删除的测试

## 4. 收缩实现绑定测试

- [ ] 4.1 将File Tool与Agent提示测试收敛为“目录候选直接物化”和“原始二进制不进入Sandbox”两个稳定安全不变量，删除对完整状态枚举和精确提示措辞的重复断言
- [ ] 4.2 删除直接调用reset私有`_clear_database_rows()`并匹配PostgreSQL SQL字符串的fake测试，保留通过公开`report/apply`验证确认、blocker、inventory drift、对象删除和数据库最终状态的测试
- [ ] 4.3 运行聚焦行为测试，确认Catalog候选物化、Manifest外metadata拒绝、固定文本格式、Docling Profile hash和文件域reset结果未改变

## 5. 验证与交付

- [ ] 5.1 运行后端受影响测试、Ruff与compileall，并确认静态搜索不存在已删除类、Registry、错误码、字段和legacy contract reset helper
- [ ] 5.2 运行前端受影响测试、lint、typecheck与build，确认管理端不依赖`runtime_assembly`或`policy_source`
- [ ] 5.3 运行`openspec validate remove-single-contract-overdesign --strict`、`docker compose config --quiet`和`git diff --check`
- [ ] 5.4 复核最终diff只包含删除和窄化，不新增配置项、兼容分支、Factory/Manager/Provider/Registry/Adapter或未来脚手架
