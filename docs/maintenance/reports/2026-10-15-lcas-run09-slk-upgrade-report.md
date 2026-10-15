# SLK 实战问题与下一版升级报告

本报告把 LCaS 本轮实战中已确认属于 SLK 的问题交给「方法负责人｜SLK」，纳入下一版升级。先去掉已证实的障碍，再修正不一致的适配和指引；不新增管理底座，不把临时恢复包装为永久修复，不把产品失败或 Supervisor 自身操作错误算成 SLK 缺陷。

## 来源和当前真实状态

- 报告日期：2026年10月15日，北京时间。
- 来源 Run：SLK-RUN-LCAS-RC08-IDENTITY-AWARE-MESSAGE-DELIVERY，内部简称 Run09。
- 实战方法：SLK 4.5.2 build2，最终 plan4；不是把当前仓库或其他版本线一概称作4.5.2。
- 来源 Supervisor 对话：01a0bed1-af60-7ac0-8003-d3d6f9d30124；接收对话：019fac68-139f-74f3-aa3d-87d1eb7bf516，「方法负责人｜SLK」。
- CELL01 经两次正式 FAIL 后拆分；最终 Required CELL01A、CELL01B、CELL02、CELL03 的 D1 均 PASS。正式 D1 总计 FAIL4、PASS4、INCOMPLETE1，无豁免。原失败和未完成历史保留，不把传输重试、原生续作或环境启动失败计成新增 D1 FAIL。
- 最终候选：0f7e25808d03691fe99485c648eede696513078f；tree：2de2bea603b7cd0809e8aed290cbd07b7058f107。
- D2 于北京时间14:57:36正式 PASS，事件 be489cfd-901c-5c25-8c04-32b666de73f7。D2新增组合用例实际执行一次并通过；此前四次是测试启动环境或临时包装失败，不是四次产品失败。
- 老 OW 完成真实末轮 cycle120，绑定已解除，获 Supervisor 两次明确停止确认后真实退出。
- Owner随后要求停止本Run后台。原SLK关闭入口已结束准确的SLK.Run与SLK.Start，两者在北京时间16:09:58均真实COMPLETED，有独立SDK新查询的close time。共享Temporal服务和其他Run未动。
- 中央RUN_CLOSED、Worker/Checker端点退役、P07可重建缓存清理和最终Main交付仍pending。工程验收通过、后台工作流关闭、中央行政归档是不同事实；本报告不把它们合并成“整Run完整关闭”。

本轮已结束产品施工和D2，方法问题由下一版集中改进。本报告不授权修改该Run历史、重跑已通过的CELL/D2、重新启动OW或部署替换本机版本。请接收者核对Owner当前版本线和升级计划后确定目标编号；若下一版属于轻量3.x线，只吸收适用原则和实现，不为了迁移这些4.x问题而把整套4.x运行组件搬进去。

## 如何区分重复问题和新缺陷

相同用户现象或同类逻辑问题即算重复，不因为错误码、message或发生CELL不同就重新计数。下文“新缺陷”表示本轮首次确证的具体缺口，不宣称此前所有版本绝不存在。历史身份错配在关闭入口再次出现，归为重复问题的新表现，不另算一个全新问题。audit74至83是同类反复告警，不是十个独立缺陷。

| 编号 | 分类 | 已确认的问题 | 最小纠正层级 |
| --- | --- | --- | --- |
| R1 | 重复 | OCRV送审仍撞8000字符硬门槛 | 现有OCRV适配入口去障碍 |
| R2 | 重复，新位置再现 | 合法恢复或旧计划证据与当前canonical来源错误匹配 | 原身份关联与只读取证适配 |
| R3 | 重复 | OW与Temporal保障持续出现同类审计失败 | 原保障链取证和收尾调用规则 |
| N1 | 本轮新确证 | REQUESTED暂停申请没有撤销出口 | 现有生命周期的最小转移补齐 |
| N2 | 本轮新确证 | OW指引字段与实际消费者不一致 | 子Skill示例和语义澄清 |
| N3 | 本轮新确证 | 关闭核验把同一实际主管回合按通知重复计为未结束调用 | 现有核验按原生实体关联和去重 |
| N4 | 本轮新确证 | OCRV原生探针输出不能被SLK自身活动校验消费 | 现有探针输出投影一致化 |

## 重复问题的证据和修正方向

### R1 任意送审门槛仍未清干净

SLK的OCRV适配代码仍包含max_background_characters=8000。本轮CELL03初次候选及返工候选均因10413字符背景，在创建模型Session之前被拒绝。provider、model、session和verdict为空，缺review-completed.json是后续包装报错，不是新的审查决定，更不是第二次正式D1 FAIL。

现场沿用已有原件索引化方式：保留完整目标、七项标准、候选和原件路径/字节数/SHA，避免重复大段背景；同一原Checker最终实际读取源码并完成判断。这证明现场能恢复，不证明8000门槛被永久移除。

下一版应首先移除SLK自行添加的任意送审拒绝门槛、避免重复背景。不得改成另一个固定数值，或通过静默截断材料“通过预检”。原生Agent或模型确有真实限制时，使用完整原件引用及Checker现有的轻量预检/分段能力，不能把平台真实限制与SLK附加门槛混为一谈。适配代码中的其他容量默认值需逐项追踪实际用途；本轮只确证8000这一项实际挡工，不把看到一个常量就说所有限制都发生过故障。

### R2 恢复来源与中央投影脱节

多个CELL中，同一注册成员、同一Session和原message的合法恢复已有真实ACTIVE证据，但run-level collector仍按原canonical failed调用或原路径/hash查找，返回UNKNOWN。独立原生inspector证明ACTIVE不等于中央关联已修好；Root没有把UNKNOWN改成正常，也没有重发工程来绕过关联。

收尾再次出现同类错误：当前plan4 Host被用于验证绑定plan1/2/3的历史native continuation，立即报“native continuation changed its exact original responsibility”。原件没有变，是读取方用错了核验上下文。

现场只在任务副本中按明确历史Host SHA选择对应冻结原Host，仍核对Run、state、原身份、原文件和原hash。初始拒绝消失，但完整关闭核验仍未通过。因此只能说修正了这一个错误，不得说“关闭已修好”。安装版SLK未变。

下一版在现有身份链中正确关联原调用、合法恢复activation和冻结计划版本；历史证据用其原版本核验，当前责任用当前版本核验。不能重写旧marker、用标题猜Session、另建身份或把原凭据检查退回自由文本。

### R3 OW和Temporal重复审计异常没有根治

OVERWATCHER_AUDIT_FAILED在本轮反复出现，已保留audit74、后续至82/83的准确通知。部分时间原OW和实际Worker/Checker确实活跃，独立原生证据与collector/审计错误并存。不能据此认定OW模型无能，也不能因为成员在工作就宣称保障链正常。

audit83的通知材料在08:01:46Z形成并投递，此时本Run的OW绑定已解除。只凭投递时间，不能断言是刚产生的审计、积压投递还是工作流仍沿用旧绑定；需要检查原Temporal事件，尚未完成定因。

最后最有效的去障碍动作不需要升级代码：Owner要求停止后台后，调用安装原slk-temporal-delivery close-run，准确原pair得到PAIR_CLOSED，独立inspector新查两执行均COMPLETED。此前把“行政核验pending”当成“后台必须继续报警”，是Supervisor处置错误，应在现有收尾指引明确纠正。

下一版沿原保障链修正真实活动采集/恢复关联，并把现有停止本Run工作流的规则写清：工程、后台和归档状态分别如实报告；不因行政堵塞无止境保留无意义监控。共享服务不能因一个Run关闭被误停；已投出的旧通知按原ID处置，不重启OW或重开工程。

## 本轮新确证缺陷

### N1 REQUESTED没有撤销路径

中央仅写RUN_PAUSE_REQUESTED，尚未确认PAUSED。原state-core和Temporal均要求REQUESTED→PAUSED→RESUMED，不能取消未生效申请；参数变化也被REQUESTED挡住。为撤销一个申请先证明全历史停稳并完成真正暂停，形成不必要障碍。

Owner明确批准一次窄范围临时修正。冻结任务副本仅补匹配pause_id/current revision的REQUESTED→RESUMED、cancel_requested:true；原权限、TOKEN、普通暂停恢复和确切身份检查保留。Rust write_flow38/38通过；Temporal纯数据四项实际RED→GREEN，真实前后workflow history回放通过。中央runtime51→52，原REQUESTED保留，没有伪造RUN_PAUSED，TOKEN仍T014，未扣未确认暂停时间，原Worker后续真实续作。

这是一项经验证的任务内修正，不是部署了正式SLK新版。下一版在现有生命周期和既有标准Tool中吸收同等最小能力，不能另做暂停管理系统。对当前轻量版本线如不适用该状态实现，应分别归档，不强塞4.x状态组件。

### N2 OW提示词与实际工具合同不一致

OW某次按指引给顶层verdict，被消费者以unknown field verdict拒绝。另一次cycle40把被观察成员的UNKNOWN误放到描述OW自身的native_liveness，消费者要求真实前台OW为IN_PROGRESS。前者是文档/工具不一致；后者还包含子Skill语义不清和模型执行混淆。

有效临时动作只是澄清：OW自身保持真实proof支持的IN_PROGRESS；观察对象UNKNOWN单独放scope和ACTIVITY_UNPROVEN。OW重新取fresh事实、用自己密封消费者写入，原cycle40成功，未改代码/身份/模型。

下一版对子Skill增加一个与当前消费者实际接受结构一致的紧凑示例，明确“观察者状态”和“观察对象状态”。保留必要身份合同，不给不支持字段编造宽松解析器，也不因此新增schema层或中继器。

### N3 关闭核验按消息重复计数实际同一个回合

第一次census的10条active/unknown通知，经各自不可变desktop-readback核对，全部指向Root同一个thread/turn，与D2协调回合完全一致，不是10个Worker。原核验仅特许一个精确coordinator来源，却没正确归并同一实际回合的通知别名，产生“主管在线核验自己已结束”的冲突。

现场自然结束一次父回合，只能消除这一活回合条件，不能修复其他旧记录读取问题；不得把它写成关闭成功或采用后台自唤醒脚本。

同一关闭操作还对90个Desktop来源反复读取仅6个实际turn。第一次约十分钟，第二次加任务内缓存后仍未完成关闭：失败MCP请求不缓存，旧观测不续时，四条过期观测仍正确保留UNKNOWN。缓存仅改善重复读取，不是永久根治。

下一版在现有核验中按精确原生实体归并指向同一回合的来源，正确识别当前主管协调实体，不强迫主管退出才能关闭其Run。旧的不同turn和实际Worker/Checker/executor仍必须核验；不能笼统排除所有Supervisor调用。单次核验按唯一实体复用真实观测，保留原observed_at，不倒灌整个历史、不刷新旧时间、不再新增定时器或另一个监控器。

### N4 OCRV探针输出与自己的消费者投影不一致

关闭census中5条OCRV记录报“native activity must use the closed task projection”。现有native_activity._file_native_probe调用inspect_ocrv_session后，所得外层投影不能满足紧接着validate_native_task_activity要求的TASK_ACTIVITY字段合同。不能把适配拒绝当OCRV还在运行，也不能因为launcher退出就猜executor停止。

下一版只修现有探针/消费者之间的投影适配，保留原Run、message、native task identity和真实观测时间。必须能区分launcher结束但executor仍活跃的情况。不得单凭completed.json、transport FAILED或“报告已有”生成STOPPED证明。

## 尚未确证的原因和不应混入的责任

第二次关闭proof实际188行：STOPPED86、STAGED_NOT_STARTED25、COORDINATING1、UNKNOWN76。UNKNOWN分为MCP请求失败40、投影不匹配5、endpoint不可读2、缺原生start/确切启动前stop证明19、原调用active/unknown6、旧活动观测stale4。这是证据行数，不是成员数或产品失败数。

40条MCP失败的旧host别名读取顺序是代码层线索，尚未验证为全部根因；2条不可读endpoint尚未定因。19条历史缺证需区分真实启动、发送后读回失败和确定启动前拒绝，不能批量改STOPPED。上述待查项不能包装成已定位、已修复的新缺陷。

以下不计为SLK已确认缺陷：

- Worker的产品遗漏、草稿宣称完成但源码未完成、报告引用路径不存在和复用草稿日志名，直接责任首先是Worker；Supervisor机械代交和指出遗漏是补救，不是正常无补救交付。
- DSH报告自述context exhaustion，尚无独立provider证据证明固定模型上限，不据此断定Flash能力不行或擅自升级Pro。
- OS升级重启有系统事件证据，是外部宿主中断；角色恢复关联是否正确属于SLK适配，不能把重启本身归给SLK。
- 测试原artifact路径PermissionDenied，复制后相同SHA的测试binary可运行；底层Windows规则未定因，不能写成SLK或OCRV根因。
- LCaS原build guard成功时未保留child stdout，是项目既有guard行为，不是已证实的SLK代码缺陷；libtest --logfile真实有效，可作为现有工具用法经验，不要求重造guard。
- Supervisor错误登记未创建的Session、误用原始文件hash与canonical JSON hash、错误source参数、裸rustfmt路径、WindowsPS Get-FileHash假设及一次巨量日志输出，均为本人操作错误，不推给SLK。下一版只在已有相关提示中给简洁正确示例，不为每个失误再加审核门槛。

## 已验证的临时办法和适用边界

| 现场动作 | 实际证明 | 不能声称 |
| --- | --- | --- |
| 输入引用完整原件，去除重复背景 | 原Checker真实启动并完成D1 | 8000门槛已永久移除 |
| 历史continuation用其原冻结Host核验 | 原历史版本拒绝消失，进入后续census | 全部停稳或行政归档成功 |
| REQUESTED最小撤销转移 | Rust38项、Temporal4项及真实历史回放通过，原Worker续作 | 正式安装版本已升级 |
| OW字段语义澄清与fresh重新观察 | 原cycle40被本人标准消费者接受 | canonical/recovery关联也同时修好 |
| 单次核验缓存精确原生turn | 重复来源复用原观测，未伪造新时间 | MCP读取失败及其他UNKNOWN全部解决 |
| 原CLI close-run准确原Temporal pair | PAIR_CLOSED及两执行真实COMPLETED/close_time | 中央RUN_CLOSED、角色归档和缓存清理也已完成 |

## 下一版的最小验证要求

优先修对应现有入口和子Skill，复用当前测试、原生接口和Temporal，不另建审批器、结果预审、轮询后台或自唤醒机制。每项以本次失败作小型回归，再做必要的真实消费者核验，不重演历史整条工程链。

1. 超过8000字符的同类资料可按完整原件引用到达原Checker，标准和证据不静默丢失；任意格式/长度不能扣住已经生成的报告。
2. 同Session合法恢复及跨冻结计划的历史证据读取正确关联；真的错身份/错hash仍拒绝，不能用宽泛放行假装兼容。
3. 未确认暂停可准确撤销；原真正PAUSED流程、TOKEN、计时及幂等性不变，不扣尚未发生的暂停时间。
4. 从OW子Skill直接照示例调用，原消费者可接受；观察者IN_PROGRESS与成员UNKNOWN可以同时如实表达。
5. 同一主管当前原生turn对应多个通知，仍只有一个协调实体，不需父回合退出；另一个真实旧writer或OCRV executor活跃时不能给QUIESCENT。
6. OCRV原生inspector输出可被实际活动消费者读取，且launcher退出/executor存活反例不误判。
7. 单次关闭核验不为同一原生实体反复全历史读取；旧观测不续命，缺证明确UNKNOWN，不靠新增时间或材料额度掩盖问题。
8. 本Run后台结束后不再安排新巡查/提醒，已投出的旧通知不重开工程；共享服务和其他Run不受影响。后台结束、中央关闭、角色归档分别有真回执。

接收后请在原对话登记报告，说明拟纳入的下一版编号/版本线、复用或已修项目、仍需验证项目。若已有Owner批准的下一版升级计划，按该计划吸收；本次传递不要求立即替换LCaS本机SLK、不改历史、不替产品重新D1/D2。在你自己的对话给确认即可，本Supervisor通过原生读取核对，无需另建中继或跨对话回传协议。

## 原始证据索引

全部路径位于本项目，不在桌面。下列SHA是发送报告前的实际文件快照；追加型记录未来变化应另存新快照，不覆盖本报告列出的事实。原自动导出是中央投影，不是手写本报告的替代品。

prepared绝对目录：D:/LCaS/.codex/.tmp/SLK-RUN-LCAS-RC08-IDENTITY-AWARE-MESSAGE-DELIVERY/prepared。

| prepared中的原件 | 字节数 | SHA256 |
| --- | --- | --- |
| cell03-method-incidents.md | 5298 | 425976bcc47a5a2322dbd3a58bc16a1db00c6cf8c0c4f998c1a9ce5efbaf2553 |
| cell03-execution-record.md | 66519 | d03b817420024a4e8b75014114db0d085a86bb35848562f3b97ff9492b502b7e |
| worker-context-recovery-20261014.md | 55930 | 787132a4ee8247e2b1de7b9b32061463184136ff50fb58d89d85aa702cece39c |
| overwatcher-cycle40-field-confusion.md | 3719 | a6c20ed3c6758711f36ffaa2232cfb30b6a8d7a95a2ae69b848f4fce16be8409 |
| d2-execution-record.md | 24399 | c3e70e492454490404255355f77773fba4ab18968dd15e5ff100b831236a42e8 |
| d2-final-acceptance.md | 7641 | ff222d98e97f0e0c1c27a85eb5a2726b019f05f194003c2408a7c7278dfb458b |
| d2-post-owclose-quiescence-20261015T0711Z.json | 1426802 | 65d3bd5aacfcaa32922bd1d3553467c7c6773c3a8797af789fafcdcbe695f6cc |
| d2-post-owclose-quiescence-20261015T0720Z.json | 1426696 | 0ba295cd76b1867368c36cff7a04a63d756fe6e2403d3921b613566243aa2a69 |
| close-run-after-d2-temporal-20261015-result.json | 186 | 6ca0f0fe4584d7be3cd9c2730a0aed29b9ac601409d7024e7c414ca550f800bb |
| run09-closure-pending-checkpoint-20261015.md | 4606 | 983d6564cbc913de5927916c368d03dffd8d2c5ad8e7bce3f10d4bf5988d32df |

中央自动导出原件：D:/SLK-Data/exports/lcas/SLK-RUN-LCAS-RC08-IDENTITY-AWARE-MESSAGE-DELIVERY/SLK-RUN-SLK-RUN-LCAS-RC08-IDENTITY-AWARE-MESSAGE-DELIVERY.md，860251字节，SHA2564048a341302dfde25f245dc2ac220d9c181fcbda7090ff96ce5b1ea6561895a1。

任务内关闭核验副本role_host.py的SHA256为0e26859169d6dcaa1f71ca7d385c4040fdc685e8147f27e5976ee19787ce2197；原安装slk-transport.pyz仍为cd861bcd0b90e929ebc93a98e8875d53928b8e64c861f8dc3c87e58749802ea3。本次报告没有修改或部署该工具。
