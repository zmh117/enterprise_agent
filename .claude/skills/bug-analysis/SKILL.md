Use this skill when a user asks for incident, defect, or business exception analysis.

Workflow:
1. Identify the business object, service, time window, and symptom.
2. Search ER and business-flow context before broad data queries.
   知识库出现相关 ONES 历史问题时，按 ones-query 的核验流程读取用于结论的工单详情和评论时间线，并实际阅读消息结果文件；核对修复版本、现场换包、回归与重开，不以已关闭替代核验。工具不可用、消息/正文截断或未读完整时明确说明工单及证据缺口。
3. Query logs, database state, and Redis cache only through approved tools.
4. Output conclusion, evidence, uncertainty, and safe next actions.

