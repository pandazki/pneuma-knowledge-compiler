import { defineMessages } from "./define";

/**
 * The Profile view: the synthetic user record, its editor, and the AI drafting flow.
 *
 * Two things deliberately stay OUT of this dictionary:
 *   - Everything the service composes — display_name, bio, occupation, interests,
 *     level_style, city / country / timezone, industry_other / role_other. That is data;
 *     it renders verbatim in whatever language it was written.
 *   - The bare enum codes shown by the "raw" selects (`zh-CN`, `metric`, `independent`, `agentic`,
 *     …). Those were never translated in the original copy either — they are the wire
 *     values, and the read-only summary quotes them as such.
 *
 * `profile.core.*` IS ours, though: the industry / role / seniority vocabulary is spelled
 * out in the client (the API ships keys only, no labels), so it is interface copy. It is one
 * flat table rather than three, exactly as the original was — `marketing` is deliberately
 * shared between industries and roles, and `other` between all three.
 *
 * The zh column is the original, hand-tuned copy, moved here verbatim.
 */
export const profile = defineMessages({
  zh: {
    "profile.header.description": "synthetic 用户档案：核心字段、编辑与 AI 生成。",
    "profile.header.descriptionShort": "synthetic 用户档案。",
    "profile.header.demoDescription":
      "演示用 synthetic 人设：由服务确定性合成，不代表真实用户。",
    "profile.onboarding.title": "新建画像",
    "profile.onboarding.description":
      "先建立工作画像；可以让 AI 生成一份可编辑草稿，也可以直接填写。",

    "profile.empty.title": "尚未选择用户",
    "profile.empty.description": "选择一个 user_id 查看其画像；任何 id 都会解析出一份合成画像。",
    "profile.error.title": "画像加载失败",

    "profile.source.prefix": "画像来源",
    // The legend follows a <Mono> chip on the same line. JSX drops the newline between them,
    // so the leading space en needs lives in the string; zh butts the full-width bracket up
    // against the chip, as it did originally.
    "profile.source.legend": "（mock = 合成，user = 已编辑保存）",

    "profile.action.edit": "编辑画像",
    "profile.section.edit": "编辑画像",
    "profile.section.core": "核心字段",
    "profile.section.confirm": "确认画像",

    "profile.ai.title": "AI 生成画像",
    "profile.ai.lead":
      "一句话描述一个人设，AI 展开为完整画像草稿并预填编辑表单——不落库，确认保存后才写入。",
    "profile.ai.inputAria": "一句话描述人设",
    "profile.ai.placeholder": "如「杭州做开源数据库的独立开发者」",
    "profile.ai.generate": "生成草稿",
    "profile.ai.failed": "生成失败：{detail}",
    "profile.draft.title": "草稿已预填",
    "profile.draft.body": "这是 AI 按一句话生成的草稿，尚未写入——确认「保存画像」后才落库。",

    "profile.group.basics": "基本",
    "profile.group.style": "回答风格（industry / role / level）",
    "profile.group.locale": "地区与偏好",
    "profile.group.workspace": "工作台",

    "profile.field.displayName": "显示名称",
    "profile.field.occupation": "职业",
    "profile.field.gender": "性别（可选）",
    "profile.field.birthYear": "出生年份（可选）",
    "profile.field.bio": "简介",
    "profile.field.interests": "兴趣",
    "profile.field.industry": "行业",
    "profile.field.industryOther": "行业（其它）",
    "profile.field.role": "角色",
    "profile.field.roleOther": "角色（其它）",
    "profile.field.level": "资历（决定 AI 回答风格）",
    "profile.field.city": "城市",
    "profile.field.country": "国家",
    "profile.field.timezone": "时区",
    "profile.field.language": "界面语言",
    "profile.field.responseLanguage": "回答语言",
    "profile.field.units": "单位",
    "profile.field.privacy": "隐私",
    "profile.field.workspaceMode": "工作模式",
    "profile.field.workspaceStack": "主要技术栈",
    "profile.field.workspaceAutomation": "自动化程度",
    "profile.field.workspaceSince": "启用日期",

    "profile.hint.interests": "多个兴趣用逗号分隔",
    "profile.placeholder.occupation": "独立软件开发者",
    "profile.placeholder.bio": "一句话介绍…",
    "profile.placeholder.interests": "开源, 编译器, 徒步",
    "profile.placeholder.industryOther": "自定义行业",
    "profile.placeholder.roleOther": "自定义角色",

    "profile.form.nameRequired": "显示名称不能为空。",
    "profile.form.saveFailedTitle": "无法保存",
    "profile.form.saveFailed": "保存失败：{detail}",
    "profile.form.save": "保存画像",
    "profile.form.cancel": "取消",
    "profile.form.skip": "跳过，先导入",

    "profile.term.industry": "行业",
    "profile.term.role": "角色",
    "profile.term.level": "资历",
    "profile.term.levelStyle": "回答风格",
    "profile.term.occupation": "职业",
    "profile.term.bio": "简介",
    "profile.term.interests": "兴趣",
    "profile.term.region": "地区",
    "profile.term.workspace": "工作台",
    "profile.term.preferences": "偏好",
    "profile.term.joinedAt": "加入时间",

    "profile.summary.mode": "模式 {value}",
    "profile.summary.stack": "技术栈 {value}",
    "profile.summary.automation": "自动化 {value}",
    "profile.summary.since": "自 {value}",
    "profile.summary.responseLanguage": "回答语言 {value}",
    "profile.summary.units": "单位 {value}",
    "profile.summary.privacy": "隐私 {value}",

    "profile.core.tech": "技术与软件",
    "profile.core.finance": "金融",
    "profile.core.sports": "体育",
    "profile.core.creative": "创意",
    "profile.core.education": "教育",
    "profile.core.healthcare": "医疗健康",
    "profile.core.marketing": "市场",
    "profile.core.engineering": "独立工程",
    "profile.core.product_management": "产品管理",
    "profile.core.sales": "销售",
    "profile.core.design": "设计",
    "profile.core.support": "客户支持",
    "profile.core.admin": "运营管理",
    "profile.core.other": "其他",
    "profile.core.entry": "入门",
    "profile.core.junior": "初级",
    "profile.core.mid": "中级",
    "profile.core.senior": "资深",
    "profile.core.staff": "专家",
    "profile.core.principal": "首席",

    "profile.levelStyle.entry": "用定义和逐步拆解解释问题，不预设背景知识。",
    "profile.levelStyle.junior": "给出清晰说明、具体例子和必要的下一步指引。",
    "profile.levelStyle.mid": "平衡结论、理由与可执行细节。",
    "profile.levelStyle.senior": "保持简洁，优先呈现取舍、影响和决策边界。",
    "profile.levelStyle.staff": "突出系统影响、跨域约束和边界情况。",
    "profile.levelStyle.principal": "默认深厚专业背景，只保留决策所需的高信号信息。",
  },
  en: {
    "profile.header.description":
      "The synthetic user record: core fields, editing, and AI generation.",
    "profile.header.descriptionShort": "The synthetic user record.",
    "profile.header.demoDescription":
      "A synthetic persona for the demo: composed deterministically by the service, not a real user.",
    "profile.onboarding.title": "New profile",
    "profile.onboarding.description":
      "Start with a working profile: let the AI draft one you can edit, or fill it in yourself.",

    "profile.empty.title": "No user selected",
    "profile.empty.description":
      "Choose a user_id to read its profile; any id resolves to a synthetic one.",
    "profile.error.title": "Could not load the profile",

    "profile.source.prefix": "Provenance",
    "profile.source.legend": " (mock = synthesised, user = edited and saved)",

    "profile.action.edit": "Edit profile",
    "profile.section.edit": "Edit the profile",
    "profile.section.core": "Core fields",
    "profile.section.confirm": "Confirm the profile",

    "profile.ai.title": "Draft a profile with AI",
    "profile.ai.lead":
      "Describe a persona in one sentence and the AI expands it into a full draft, pre-filled into the form below — nothing is stored until you save.",
    "profile.ai.inputAria": "Describe the persona in one sentence",
    "profile.ai.placeholder": "e.g. “an indie developer in Hangzhou building an open-source database”",
    "profile.ai.generate": "Generate a draft",
    "profile.ai.failed": "Generation failed: {detail}",
    "profile.draft.title": "Draft pre-filled",
    "profile.draft.body":
      "This is the AI's draft of your one-line description. Nothing is written yet — it lands only once you choose “Save profile”.",

    "profile.group.basics": "Basics",
    "profile.group.style": "Answer style (industry / role / level)",
    "profile.group.locale": "Region and preferences",
    "profile.group.workspace": "Workspace",

    "profile.field.displayName": "Display name",
    "profile.field.occupation": "Occupation",
    "profile.field.gender": "Gender (optional)",
    "profile.field.birthYear": "Year of birth (optional)",
    "profile.field.bio": "Bio",
    "profile.field.interests": "Interests",
    "profile.field.industry": "Industry",
    "profile.field.industryOther": "Industry (other)",
    "profile.field.role": "Role",
    "profile.field.roleOther": "Role (other)",
    "profile.field.level": "Seniority (sets the AI's answer style)",
    "profile.field.city": "City",
    "profile.field.country": "Country",
    "profile.field.timezone": "Time zone",
    "profile.field.language": "Interface language",
    "profile.field.responseLanguage": "Answer language",
    "profile.field.units": "Units",
    "profile.field.privacy": "Privacy",
    "profile.field.workspaceMode": "Operating mode",
    "profile.field.workspaceStack": "Primary stack",
    "profile.field.workspaceAutomation": "Automation level",
    "profile.field.workspaceSince": "Active since",

    "profile.hint.interests": "Separate interests with commas",
    "profile.placeholder.occupation": "Independent software developer",
    "profile.placeholder.bio": "One sentence about yourself…",
    "profile.placeholder.interests": "open source, compilers, hiking",
    "profile.placeholder.industryOther": "Your own industry",
    "profile.placeholder.roleOther": "Your own role",

    "profile.form.nameRequired": "A display name is required.",
    "profile.form.saveFailedTitle": "Cannot save",
    "profile.form.saveFailed": "Save failed: {detail}",
    "profile.form.save": "Save profile",
    "profile.form.cancel": "Cancel",
    "profile.form.skip": "Skip, import first",

    "profile.term.industry": "Industry",
    "profile.term.role": "Role",
    "profile.term.level": "Seniority",
    "profile.term.levelStyle": "Answer style",
    "profile.term.occupation": "Occupation",
    "profile.term.bio": "Bio",
    "profile.term.interests": "Interests",
    "profile.term.region": "Region",
    "profile.term.workspace": "Workspace",
    "profile.term.preferences": "Preferences",
    "profile.term.joinedAt": "Joined",

    "profile.summary.mode": "mode {value}",
    "profile.summary.stack": "stack {value}",
    "profile.summary.automation": "automation {value}",
    "profile.summary.since": "since {value}",
    "profile.summary.responseLanguage": "answer language {value}",
    "profile.summary.units": "units {value}",
    "profile.summary.privacy": "privacy {value}",

    "profile.core.tech": "Technology and software",
    "profile.core.finance": "Finance",
    "profile.core.sports": "Sport",
    "profile.core.creative": "Creative",
    "profile.core.education": "Education",
    "profile.core.healthcare": "Healthcare",
    "profile.core.marketing": "Marketing",
    "profile.core.engineering": "Solo engineering",
    "profile.core.product_management": "Product management",
    "profile.core.sales": "Sales",
    "profile.core.design": "Design",
    "profile.core.support": "Customer support",
    "profile.core.admin": "Operations",
    "profile.core.other": "Other",
    "profile.core.entry": "Entry",
    "profile.core.junior": "Junior",
    "profile.core.mid": "Mid",
    "profile.core.senior": "Senior",
    "profile.core.staff": "Staff",
    "profile.core.principal": "Principal",

    // Verbatim from domain/user.py::LEVEL_STYLES, so this hint and the `level_style` the
    // service returns (rendered as data, one field away) read as the same sentence.
    "profile.levelStyle.entry": "Prefers thorough, step-by-step explanations with definitions.",
    "profile.levelStyle.junior": "Prefers clear explanations with examples and some guidance.",
    "profile.levelStyle.mid": "Prefers balanced answers with rationale and practical detail.",
    "profile.levelStyle.senior":
      "Prefers concise, context-aware answers that focus on trade-offs and impact.",
    "profile.levelStyle.staff":
      "Prefers high-signal answers emphasizing systemic implications and edge cases.",
    "profile.levelStyle.principal": "Prefers terse, decision-oriented answers assuming deep expertise.",
  },
});
