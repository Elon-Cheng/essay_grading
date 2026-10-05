# Word 导出与交付校验

基于 output-format.md 的同一份 grading.md 导出，不改变网页数据结构。

## Word 渲染与交付

以本次输入 DOCX 的副本为底稿，保留题目、学生信息、版式、非作文内容及文档部件。输入不变，结果写入新文件；不使用旧结果或空白文档代替底稿。

运行 scripts/render_grading_docx.py，传入 source-docx、source-md、grading-md、output-docx。原文及被删除文字黑色，删除线红色；新增文字与教师批注红色，保持正文字号，不增加绿色／黄色格式或分类标签。

交付必须同时通过：source_docx_match、source_base、reversibility、content_match、format。逐字可逆原文、段落顺序、实际修改、点评、评分和表格均与本次 Markdown 对应；不含旧评语、乱码、粘连或字面量反斜杠n。失败时修正后从原始底稿重新生成，不能仅凭文件可打开就交付。
