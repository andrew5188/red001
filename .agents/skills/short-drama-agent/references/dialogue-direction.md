# 对白归属与口型

有对白、唱词或画外人声时读取。官方字段与标签仍用相邻h3-prompt-writing技能；本文件的计划只存project.json，不添加H3顶层字段。

## 先分配台词，再设计镜头

每句明确唯一说话角色、声音ID、原文、起止时间、可见说话人口部及听者行为。多人同声或交叠必须是剧情明确需要并记录理由，不能默认多人一起说同一句。声音ID和Subject标签是文字指导，不是模型硬绑定。

通常用说话人的单人近景、过肩或侧后方听者构图，让听者口部不正对镜头；在话音后的停顿给听者眼神、呼吸和表情反应。多人全景可交代关系或共同动作，不能为了连续性固定整段双人正脸讲话。需要双人正脸的具体镜头记录创作理由，并提高听者口型检查密度；不机械禁止所有双人镜头。

多句换人时明确切镜与短停顿，单句只出现一次。按可说完的速度安排时段；不在10秒里塞入过多对答。保留剧情动作和自然互动，不为隔离口型把所有场景改成孤立头像。

人物关键帧、可见人数、实际参考槽与口部可见性同步设计。若问题来自双人正脸首尾图，重新派生镜头图，不只追加“只有他讲话”。不默认把两张不同人的正脸图绑定成同一个镜头的首尾，以免形成人物变形。

## 项目数据与执行检查

片段dialogue_plan保存status=ready和lines（无台词时为空列表）。每条包含id、speaker_character_id、voice_id、text、start_seconds、end_seconds、framing、visible_mouth_characters、listener_behavior。framing可用speaker_closeup、over_shoulder、offscreen、two_shot或ensemble。two_shot需framing_reason；有意重叠另设intentional_overlap=true及overlap_reason。角色和口部列表使用真实角色ID；画外发声者不在口部列表中；若画面有听者正脸仍登记其口部，并检查没有跟说。

准备与提交都调用scripts/quality_gates.py的require_input_quality，并将dialogue_plan、action_plan.staging及检查脚本指纹纳入输入快照。input_review记录quality_policy_version=1和checks.dialogue=passed（有对白时）；不能凭脚本结构校验冒称参考图与语义已审。

## 逐句验收

为每句保存output_review.line_reviews，包含line_id、visual_status、audio_status和evidence。按真实声音段检查前后口型、听者、换人点和停顿；不能只靠每半秒抽帧推断完整口型同步。证据说明实际时段、方法、文件或观察，区分音轨叠声、听者跟口型及两者同时发生。

有对白的新输出必须checks.dialogue_visual=passed；每句visual_status=passed。用可用试听或分析检查台词、说话人和重复声部。ASR、声音峰值、音轨存在均不能单独证明声音属于正确人物；人工或自动分析的能力与盲点分别记录。

无主观音频检查能力仍沿用已授权首段后策略：audio_status=waived且明确未验证，不能把它写成音频归属已通过。听者明显跟口型属于可见错误，不能音频豁免。用户已报告的台词串人/叠说属于已知问题；先定位、修复并以对应证据解决问题，不能依赖之前首段确认或waived继续。

缺能力时优先在已授权范围采用可检查的单人发声构图、拆分对答或核实可用的分轨/口型方案。必要画面项仍无法验证则停止受阻链并报告具体缺口，不自动添加逐段人工审批。已有项目首段与首次武戏确认策略保持不变。
