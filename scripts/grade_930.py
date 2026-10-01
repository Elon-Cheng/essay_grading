"""Build the 9.30 grading Markdown from verified source transcripts."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / "output" / "9.30"
RUBRIC = """| 档次 | 内容 | 语言 | 组织结构 |
|---|---|---|---|
| A | 9–10 | 9–10 | 4–5 |
| B | 7–8 | 7–8 | 3 |
| C | 5–6 | 5–6 | 2 |
| D | 3–4 | 3–4 | 1 |
| E | 0–2 | 0–2 | 0 |"""

DATA = {
    "2027 春考冲刺班-戴子钧-作文 5-第 1 遍": {
        "task": "文章面向一般读者，需分析忙碌生活中产生心理健康问题的原因，并提出保持心理健康和快乐的方法。提纲列出社会压力、网络环境及三项应对办法，正文基本按此展开；但对“平衡”的具体解释仍较少，末段也未收束全文。议论语体基本合适。正文约274词，符合250–300词要求。",
        "score": 17,
        "bands": ("B", "C", "B"),
        "overall": "文章能把社会竞争、网络伤害与目标管理、求助支持联系起来，提纲中的主要方向也落实到了正文。最影响提升的是第二段把人口增长直接等同于资源紧缺，却没有足够解释，且多个长句的主谓结构和搭配不稳；第三段过渡后分列三项建议，篇末缺少归纳。下次先给每个原因补一条具体作用机制，再检查长句的谓语和逻辑主语；结尾用一句话说明这些方法如何共同帮助人们恢复生活平衡。",
        "notes": {
            0: ([("In the fast pace of modern life", "In fast-paced modern life")], "开头提出快节奏生活与心理健康的关联，并明确后文讨论方向；但“心理疾病日益普遍”属于较强判断，最好简要指出日常压力或休息不足如何造成困扰，使引入更有根据。", ["`in the fast pace of modern life` 把名词 `pace` 当作形容词修饰语，应改为：`in fast-paced modern life`。`fast-paced` 表示“节奏快的”。"], "先用一个可观察的忙碌场景引出问题，再提出中心论点。训练时给开头的宽泛判断补一条具体表现，避免只用“日益普遍”作铺垫。"),
            1: ([("which acts as a tangible force pushes us", "which acts as a tangible force pushing us"), ("the status of overwhelming", "a sense of being overwhelmed"), ("which also acting as a major contributor to mental troubles is the advanced online world", "the advanced online world also contributes to mental troubles"), ("high spreading spread", "rapid spread"), ("anonymous identity", "anonymity")], "本段安排了社会压力和网络伤害两条原因线，网络匿名性引向网络霸凌的思路较清楚。人口增长、资源有限和个人耗竭之间的因果被压得太紧；可以用考试、求职或工作任务中的一个具体场景把压力如何产生说清楚。", ["`a tangible force pushes us` 前已有关系从句的谓语 `acts`，后面不能再直接接 `pushes`，应改为：`a tangible force pushing us`。", "`the status of overwhelming` 词形和搭配均不成立，应改为：`a sense of being overwhelmed`。`overwhelmed` 描述人的感受。", "`which also acting ... is` 缺少合适的主句结构，应改为：`the advanced online world also contributes to mental troubles`；`high spreading spread` 重复且搭配错误，应改为 `rapid spread`。"], "把“社会竞争”落到一个可观察的压力来源，再说明它怎样剥夺休息。练习时把每个复杂句划成主句与修饰部分，逐一检查谓语是否完整；记录 `rapid spread`、`a sense of being overwhelmed` 这样的完整词块。"),
            2: ([], "这一段把原因分析转向应对办法，过渡功能明确，但单独成段只预告“有几种方法”，信息量较少。可并入下一段开头，或在此说明接下来为何需要同时调整目标、网络行为和求助方式。", ["`It is high time that we should...` 可以见到，但在较正式议论中 `It is high time we took action...` 更紧凑；这里可以保留原意，避免再叠加 `undesirable situation of increasing cases`。"], "独立过渡段应提供实质性的承接，而不只是宣布有办法。练习提纲时给每段写一句“它新增了什么信息”，无法回答的过渡段可并入相邻段。"),
            3: ([], "本段先提出设定现实目标，再写工作与休息的平衡及爱好，回应了题目的“忙碌生活”。不过方法仍偏概括，补一个如何调整目标或安排休息的短例子，会让建议更可执行。", ["`reserve time for hobbies` 意思清楚，可以保留；若想更贴近日常安排，可写 `set aside time for hobbies`。"], "可把“设定现实目标”具体化为限定每日任务数量或安排固定休息时段。平时按“建议—实施动作—预期效果”写三句短段，积累可操作的健康建议。"),
            4: ([], "网络段承接前文的网络霸凌原因，既劝人避免冲动发言，也提醒受害者求助，内容有双向意识。不过一句话同时写施害者与受害者，角色切换较快；可分别说明“发言前核实和克制”与“遭遇攻击时保存证据并求助”。", ["`manage online behaviors` 能理解，但泛指个人网络行为时常说 `manage our online behavior`；`stay away from cyberbullying` 可保留，不过最好明确指避免参与还是避免接触。"], "把线上行为建议按“自己发言”和“受到攻击”两种情境分开，每种各给一个行动。积累网络安全主题表达时，可用情境卡记录行为、风险和应对。"),
            5: ([], "末段强调向亲友或专业人士求助，并指出及时支持的重要性，有实际价值。不过它仍是第三项建议，没有把全文原因和方法收束到“如何取得平衡”；末尾可再概括目标调整、健康上网与求助的共同作用。", ["`professional psychologists` 表达可以成立；更常见的求助对象还可说 `mental health professionals`。原句不必为了词汇升级而改动。"], "结尾建议从三种行动中提炼共同原则，例如不要独自承受持续压力。练习时先列出正文三项方法，再用一句总括句说明它们如何共同支持心理健康。"),
        },
    },
    "2027春考冲刺班-万可-作文3-第1遍": {
        "task": "这是以王磊身份写给校长的消防演习建议邮件，需指出原方案可改进处、提出可执行安排并说明理由。正文提出时长、疏散路线和灭火环节三项建议，理由较充分，邮件语体基本得当。输入文件中的原方案图表未出现在可提取正文中，因此对“十分钟”“要求学生灭真火”等细节是否准确只能依据学生转述暂定。正文约252词，符合250–300词要求。",
        "score": 21,
        "bands": ("A", "B", "A"),
        "overall": "邮件的三项建议各自对应一个安全问题，尤其25分钟分配与疏散路线的具体安排可供校方直接参考，理由也紧扣演习目的。需要注意的是，原方案细节无法从文件正文核实，提交前应逐项对照图表；语言上主要是少量标点和结尾表达。下次可继续保持“问题—调整—安全收益”的写法，并检查图表信息与建议一一对应。",
        "notes": {
            0: ([], "称呼对象明确，格式基本合适。", [], ""),
            1: ([], "开头交代身份、来意和三项改进建议，收信人能迅速把握邮件目的。若原方案的关键安排在图表中，建议在提出建议前简要点明总体目标，方便校长理解修改原则。", ["`share my opinions on` 语法成立；向校长提出方案时，`suggest changes to the fire drill plan` 会更直接。"], "开头已足够简洁；下一次读图写作先列出图中三条可核对的信息，再决定邮件的三项建议，避免把推断当成原方案事实。"),
            2: ([("As a result the firefighter", "As a result, the firefighter")], "这一段指出演习时间短，并把25分钟分配到疏散、示范和总结，具体且可执行。需要核对的是原方案是否真的只有十分钟，以及示范是否需要另留学生提问时间；数字安排越具体，越要与题图一致。", ["`As a result` 作句首连接语后应加逗号，应改为：`As a result, the firefighter...`。", "`will rush out` 可能暗示无序冲出；若想强调有序疏散，可用 `will need time to evacuate and line up`。原句并无语法错误。"], "核对图表中的时长后，再用“总时长=各步骤时长”检查数字是否自洽；做时间规划类题时，可练习用一句话解释每一步为什么需要该时长。"),
            3: ([], "本段从楼梯、集合点、引导人员三个缺口切入，再给出班级路线、教师站位和班长清点人数，建议与风险一一对应。若题图已有部分路线，需确保这三点针对的是实际遗漏而非重复原方案。", ["`Clear order can prevent crowding` 可以理解；若想更准确表达管理方案，可说 `Clear instructions can prevent crowding`。"], "把每项安排与相应风险配对，如路线对应拥堵、清点人数对应遗漏。平时练习读图后做“原方案已有／尚缺／我的修改”三列表，确保建议有针对性。"),
            4: ([], "这里把“不让学生接触真火”与“安全逃生优先”联系起来，理由有说服力，模拟练习也保留教学价值。仍需核对原图是否要求学生实际灭火；如无此要求，建议应改为强调安全示范和监督。", ["`practice the steps without real flames` 表达准确；`our first task is to escape safely` 与消防演习的重点相符，可以保留。"], "将“演示”与“学生实操”区分清楚，写安全类建议时明确谁操作、谁监督、是否使用真实危险源；这样理由与方案更可靠。"),
            5: ([], "礼貌收尾能完成请求，但只表达希望被考虑，没有回扣三项建议共同改善的安全性。可用半句概括改动目标，使结尾更完整。", ["`receive your favorable consideration` 可理解，但略显套语；更直接的邮件结束语是 `I would appreciate your consideration of these suggestions.`"], "结尾简短重申安全、秩序和操作性即可。练习正式邮件时准备两三种自然的请求句，避免反复使用过长的礼貌套语。"),
            6: ([], "署名与正文连在同一行，正式邮件宜把落款和姓名分行。", [], ""),
        },
    },
    "2027春考冲刺班-万可-作文4-第1遍": {
        "task": "这是以李华身份向校报投稿，要求描述本人或他人被贴标签的经历，并发表对贴标签的看法。文章以“书呆子”的个人经历切入，随后讨论归属感与刻板印象，两个必答点均有回应；但个人经历与后文观点的联系还可更紧。正文约212词，考场作文要满足250–300词。",
        "score": 18,
        "bands": ("B", "B", "A"),
        "overall": "文章用被称作“nerd”的经历回应题目，并用“book lover”和“lazy”展示标签的两面性，四段结构清楚。主要限制是字数偏短，个人经历只写到感到孤立，没有说明后来如何看待或处理这个标签，正反观点也因此有些抽象。下次围绕个人经历增加一个具体互动及自己的反应，再把它与“标签既可连接同伴也可限制成长”的判断扣紧；同时检查邮件投稿的称呼和署名格式。",
        "notes": {
            0: ([], "称呼与投稿对象相符。", [], ""),
            1: ([], "开头用自己因爱读书而被叫作“nerd”的经历回应必答点，感受也明确。经历停在“孤立和困惑”，还缺少是谁在什么场合贴标签、它怎样影响自己的具体细节，因而后文观点缺少亲历支撑。", ["`tagged as a nerd` 可用；如果想让校报投稿更自然，可写 `labelled a nerd`。原句语法并无问题。"], "补一件具体小事，例如同学如何看待你的阅读兴趣，以及你如何回应。训练时用“场景—他人反应—我的感受”写三句经历，再连接观点。"),
            2: ([], "本段承认标签能帮助识别兴趣并形成归属感，“book lover”与开头的阅读经历形成呼应。问题是“简化理解”与“找到同伴”之间还缺一步：标签怎样促成真实交流。可补一个由共同阅读兴趣开始交谈的具体场景。", ["`a proper label` 语法成立，但 `a positive label` 更能突出此处的有益一面；`form new friendships` 自然，可保留。"], "把“book lover”扩展成可观察的同伴交流，而不是只停在结果判断。练习论证时在抽象好处后补“谁做了什么”，提高例子的支撑力。"),
            3: ([], "本段依次说明刻板印象、维持好标签的压力和“懒惰”标签的自我实现效应，负面分析较完整。不过三项并列得较快，可选其中一项与自己的“nerd”经历相连，避免正反两段像通用观点清单。", ["`for we may feel exhausted` 语法可成立，`for` 在这里较书面；若想更自然，可写 `because we may feel exhausted...`。", "`self-fulfilling prophecies` 使用准确；若要帮助读者理解，可接上学生放弃努力这一结果，当前例子已经做到。"], "选一个与自身经历最相关的负面影响展开因果，不必平均写三项。可积累“贴标签—他人期待—个人行为”这一链条的真实校园例子。"),
            4: ([], "结尾概括了接受积极影响与避免被负面标签束缚，立场清楚。但“做真实的自己”较宽泛；可以回到“nerd”的例子，说明评价不该决定一个人的全部身份，使首尾更紧。", ["`treat labels rationally` 意思清楚；`negative tags` 与前面的 `labels` 同义，但统一用 `labels` 会更稳妥。"], "用自己的经历收束观点，比如承认阅读爱好，同时拒绝由单一标签定义自己。写结尾时检查它是否回应了开头的具体经历。"),
            5: ([], "落款格式符合投稿邮件。", [], ""),
            6: ([], "署名身份正确。", [], ""),
        },
    },
    "2027春考冲刺班-于欣源-作文5-第1遍": {
        "task": "文章面向一般读者，需说明忙碌生活中心理问题的成因及维持心理健康和快乐的方法。提纲列出竞争压力、负面信息和线下交流减少，以及工作休息安排、自我调节和沟通三种应对；正文基本逐项落实，议论语体合适。正文约278词，符合250–300词要求。",
        "score": 19,
        "bands": ("B", "B", "A"),
        "overall": "提纲和正文对应较好，原因与方法大体形成压力—作息、孤独—沟通的呼应，篇章清楚。要进一步提高，第二段需要说明负面信息如何具体引发自我怀疑，第三段也应把“合理安排”落实到一个可执行的日程动作；`there is countless negative information`、`These negative news` 等可数性问题会削弱语言准确度。下次写完先检查不可数名词的限定词，再为每项建议补“具体做法—预期效果”。",
        "notes": {
            0: ([], "开头以学生考试和成人工作压力并举，把忙碌生活具体化，也自然引出心理健康主题。只是第三句基本重复第一句的“现代社会快节奏”，可缩减背景，把篇幅留给中心论点。", ["`are buried in endless exams and exercises` 能理解，但 `buried in` 更常搭配 `work` 或 `assignments`；若要更自然，可写 `face a constant stream of exams and assignments`。"], "减少重复背景后，直接点出下文将从压力、信息环境和人际联系解释问题。练习开头时标出每句新增的信息，若两句作用相同就合并。"),
            1: ([("there is countless negative information", "there is a great deal of negative information"), ("These negative news", "This negative news")], "本段按竞争压力、网络内容和线下沟通减少三条线解释心理问题，覆盖面较完整。第一条的休息被剥夺与焦虑关系清楚；负面信息为何会造成自我怀疑则说得较笼统，可举一次社交媒体比较或不实信息影响判断的情境。", ["`information` 不可数，`countless` 通常修饰可数名词；这里应改为：`there is a great deal of negative information`。", "`news` 也不可数，不能说 `These negative news`，应改为：`This negative news`。记住 `information` 和 `news` 都不加复数 `-s`。", "`low self-esteem` 搭配准确；但 `wrong values` 较笼统，若指不现实的成功标准，可更具体地说明信息内容。"], "给网络比较补一个可观察的例子，并写明“看见什么—产生何种判断—造成什么情绪”。平时建立不可数名词卡片，记录 `a piece of news`、`a great deal of information` 等完整搭配。"),
            2: ([("Despite the above reasons", "In response to these causes")], "方法段依次提出作息安排、自我接纳和亲友沟通，分别回应上段的压力与孤独，结构有条理。不过网络负面信息在方法段没有直接对应的应对措施；可补一句限制刷屏时间或辨别比较性内容。", ["`Despite the above reasons` 表示“尽管有上述原因”，与后面提出应对办法的逻辑不吻合，应改为：`In response to these causes`。", "`a proper daily schedule` 语法成立；若想让建议更可执行，可写清学习或工作时段与休息时段如何安排。"], "为负面信息补一项行动，并让每条办法明确对应前文的一条原因。可用两列表把“原因”和“具体应对”逐项配对，避免只在原因段出现某一问题。"),
            3: ([], "结尾回到“心理健康是幸福生活的基础”，与题目呼应。但第二句几乎复述任务要求，缺少对三种方法的提炼；可概括“给休息留空间、减少无益比较、保持真实联系”怎样共同构成平衡。", ["`in the busy life` 泛指忙碌生活时，`in a busy life` 更自然；原句仍可理解，不必在原文中强制改动。"], "结尾尝试概括正文方法之间的共同原则，而非重说“保持平衡很重要”。练习时只看各段主题句，写一句能统领它们的结论。"),
        },
    },
    "2027春考冲刺班-戴子钧-作文6-第1遍": {
        "task": "这是以李明身份写给学生会的邮件，应介绍当前使用 AI 的一个有趣或有效实例，并提出感兴趣的课程内容和学习方式。提纲安排海报设计、课程内容、教师指导；正文都覆盖，邮件目的明确，但课程内容与个人实例都集中在 AI 绘图，范围略窄。正文约250词，符合250–300词要求。",
        "score": 18,
        "bands": ("B", "B", "A"),
        "overall": "邮件中的艺术节海报经历具体，能解释 AI 如何帮助探索不同风格；课程建议也分别写到内容与小组实践，任务要点完整。主要问题是开头有拼写、主谓和句子结构错误，第四段 `Such practical activities that will...` 是残句；课程内容还可以从个人绘图经历进一步扩展到判断 AI 输出是否可靠。下次写完逐句检查主语和谓语，再让课程建议至少包括一项与实例不同的学习内容。",
        "notes": {
            0: ([], "称呼表达对象基本清楚；写给学生会时可直接称 `Dear Student Union,`，比 `Dear school committee:` 更贴合题目。", [], ""),
            1: ([("optional couse", "elective course"), ("it greatly arouse", "it has aroused"), ("full interest", "interest"), ("with my reasons listed below。", "and share my suggestions.")], "开头表明对新课程感兴趣，但最后预告“下面列出理由”，实际正文还包括个人经历、课程内容与学习方式建议，预告范围偏窄。可把来意明确为分享使用经历并提出两方面建议。", ["`couse` 拼写错误；学校选修课应写 `elective course`。", "主语 `it` 后的动词形式不能用 `arouse`，此处应改为：`it has aroused my interest`；`full interest` 也不自然。", "原句结尾用了中文句号，且 `reasons listed below` 不能概括后文的建议，应改为：`and share my suggestions.` 修改后整句仍应表达加入课程和提供建议这两个目的。"], "开头用一句话概括正文结构：亲身实例、课程内容、学习方式。做正式邮件练习时，写完正文再回看开头的预告是否与实际内容一致，并检查专名、拼写和句末标点。"),
            2: ([], "艺术节海报是具体、可信的使用实例，“输入描述—比较风格—修改设计”的过程能体现 AI 的效率和趣味性。若能补一句最终海报怎样因这些尝试而改进，实例的“有效”程度会更可见。", ["`abstract conceptions` 和 `striking visual artworks` 表意清楚，但词语较密；高中邮件可简化为 `ideas` 和 `images`，让重点落在实际设计过程。", "`refine my design` 用得准确，可保留；它提示读者 AI 结果仍需人工选择与修改。"], "为案例补一个具体成果，例如比较几种版式后确定最终设计，而不是只说印象深刻。练习叙述经验时按“任务—使用过程—结果”三步写，每步保留一个可观察细节。"),
            3: ([("apply AI creations into daily life", "use AI creations in daily life")], "本段提出教授操作之外的实际应用，也提醒辨别 AI 的优势与局限，方向合理。不过海报、插画和日常作品都属于视觉创作，课程内容略重复；可以增加一项核查生成内容或尊重版权的学习主题。", ["`apply ... into daily life` 搭配不成立，`apply` 通常与 `to` 连用；如果说把作品用于生活，可改为：`use AI creations in daily life`。", "`avoid over-reliance on it` 表达准确，但前面的 `strengths and limits` 可以再举一项具体的局限，增强说服力。"], "把课程建议分成“创作技能”和“判断与责任”两类，各给一项课堂任务。积累 AI 主题词汇时把动词和介词一起记，如 `apply a method to a task`、`use a tool in daily life`。"),
            4: ([("during practicing", "during practice"), ("Such practical activities that will", "Such practical activities will")], "讲授与小组动手项目结合，且提出教师及时指导，回应了题目要求的学习方式。若说明每组最后交付什么作品、教师在哪一步给予反馈，课程安排会更可执行。", ["`during practicing` 在此不自然，应改为：`during practice`。", "`Such practical activities that will...` 多了关系词 `that`，导致整句没有主句谓语，应改为：`Such practical activities will...`。"], "给小组项目设定一个具体产出，例如校园活动海报及修改说明，并说明教师反馈的时机。自检时把每句主语和谓语划出来，看到 `that` 引出的从句，要确认整句仍有主句。"),
            5: ([], "结尾礼貌表达希望被采纳，也呼应对课程的期待。可简短重申最希望学生会考虑的一个建议，使邮件的行动请求更明确。", ["`Looking forward to the upcoming optional course.` 作为邮件结尾可理解；若要用完整句，可写 `I look forward to the upcoming elective course.`。"], "结尾优先突出一项最重要的课程安排，例如小组实践或教师指导。练习写建议邮件时检查最后一句是否让收信人知道下一步该考虑什么。"),
            6: ([], "落款与邮件体裁相符。", [], ""),
            7: ([], "署名与题目身份一致。", [], ""),
        },
    },
    "2027春考冲刺班-沈霁菲-作文2-第1遍": {
        "task": "这是以高三学生李华身份向学生会提交心理健康活动方案的邮件，应说明活动创意及设计理由。正文提出邀请心理专家讲座、提前收集学生困扰，并解释高三压力背景，任务方向正确；但活动流程和保密措施尚不够具体。正文约220词，考场作文要满足250–300词。",
        "score": 16,
        "bands": ("B", "C", "B"),
        "overall": "文章提出“事先收集问题，再由专家讲座回应”的活动思路，有针对性，也解释了高三学生面临的压力。当前最影响得分的是活动设计仍停在讲座层面：学生如何匿名提问、专家如何回应、是否安排后续求助都未说明；正文也不足250词。语言上 `enable the expert know`、`which is benefit to` 等结构需纠正。下次先写清活动流程和隐私保护，再用“主语—谓语—宾语／补语”检查每个复杂句。",
        "notes": {
            0: ([], "称呼与投稿对象一致。", [], ""),
            1: ([], "开头交代身份和来意，能让学生会明白这是活动建议。`humble opinions` 与 `might hopefully` 一起使语气过于犹豫；内容上可以更直接地预告你建议的是一场针对常见心理困扰的讲座。", ["`voice my humble opinions` 语法成立，但正式建议邮件可更直接写 `share a proposal`；`might hopefully` 同时表达两层不确定，保留一个即可。"], "开头用一句话说明建议的活动类型，让读者带着明确期待看正文。练习申请或建议邮件时，先写“我建议什么”，再补礼貌语。"),
            2: ([("enable the expert know", "enable the expert to know"), ("their trouble in study", "their troubles in study")], "讲座前收集学习、关系和家庭方面的问题，是本篇最有价值的设计，能帮助专家了解学生需求。心理困扰涉及隐私，不能直接“要求”学生提交；应说明自愿、匿名收集，并安排专家围绕高频问题作答。", ["`enable` 后接人和不定式，应改为：`enable the expert to know`。", "这里列的是多种学习与生活困扰，`trouble` 用复数更清楚，应改为：`their troubles in study, relationships and family life`；原文其余并列内容可保留。", "`fight against mental issues properly` 意思能理解，但讲座对象是普通学生时，可更稳妥地说 `cope with stress and emotional difficulties`，避免把所有困扰都说成疾病。"], "将“收集问题—分类整理—专家回应—后续支持”写成四步流程，并注明自愿匿名。平时积累校园活动方案时，列出目标对象、时间、形式和隐私保障四项检查点。"),
            3: ([("from the anxiety", "from anxiety"), ("Psychological lecture", "A psychological lecture"), ("which is benefit to", "which is beneficial to")], "本段从升学压力、家庭期待和同伴关系解释讲座的必要性，理由与活动目标相关。但 `Parents always...`、`friends don't...` 把情况说得太绝对，且没有说明讲座具体怎样帮助这些不同问题；可把例子收窄为“部分学生”，再说明专家会教什么应对方法。", ["泛指焦虑情绪时 `anxiety` 通常不加 `the`，应改为：`free themselves from anxiety`。", "`lecture` 是单数可数名词，这里需要冠词，应改为：`A psychological lecture`。", "`be benefit to` 词性错误；`beneficial` 是形容词，应改为：`which is beneficial to their personal development`。也可说 `which benefits their personal development`。"], "把“所有学生”改为可验证的部分学生情境，再给一条讲座可教授的实际技能，如识别压力信号或练习求助。练习时圈出 `always`、`all` 等绝对词，检查有没有足够证据。"),
            4: ([], "结尾再次推荐讲座并礼貌请求考虑，但没有概括这场活动的独特设计，即提前收集学生问题。可在结束前用半句回扣匿名提问与针对性回应。", ["`mental activity` 在此不够明确；若想更准确，可写 `mental health activity`。原句尚可理解，因此放在表达提升中。"], "结尾点出讲座为何优于一般宣讲，例如它回应学生预先提交的真实困扰。练习写活动建议时，最后一句回看方案最有辨识度的一步。"),
            5: ([], "邮件落款形式基本合适。", [], ""),
            6: ([], "署名与题目要求一致。", [], ""),
        },
    },
}


def mark(text, edits):
    for old, new in edits:
        if old == new:
            continue
        if text.count(old) != 1:
            raise ValueError(f"Edit is not unique: {old!r}")
        text = text.replace(old, f"~~{old}~~{{++{new}++}}", 1)
    return text


def build(name, data):
    source = (ROOT / f"{name}-原文.md").read_text(encoding="utf-8")
    paragraphs = [p.strip() for p in source.split("## Essay", 1)[1].strip().split("\n\n") if p.strip()]
    sections = ["#### 审题情况", data["task"]]
    for i, original in enumerate(paragraphs):
        edits, comment, language, advice = data["notes"].get(i, ([], "", [], ""))
        sections.extend(("#### 原文及红色修改", mark(original, edits)))
        if comment:
            sections.extend(("#### 段落点评", comment))
        if language:
            sections.extend(("#### 语言提升", "\n".join(f"{j}. {item}" for j, item in enumerate(language, 1))))
        if advice:
            sections.extend(("#### 问题建议", advice))
    sections.extend(("#### 全文综合评价和提升建议", data["overall"], f"本篇文章打分估计为：{data['score']}分"))
    rubric = RUBRIC
    for col, band in enumerate(data["bands"], 1):
        lines = rubric.splitlines()
        row = next(i for i, line in enumerate(lines) if line.startswith(f"| {band} |"))
        cells = lines[row].split("|")
        cells[col + 1] = " [[red]]" + cells[col + 1].strip() + "[[/red]] "
        lines[row] = "|".join(cells)
        rubric = "\n".join(lines)
    sections.append(rubric)
    (ROOT / f"{name}.md").write_text("\n\n".join(sections) + "\n", encoding="utf-8")


if __name__ == "__main__":
    for filename, grading in DATA.items():
        build(filename, grading)
        print(filename)
