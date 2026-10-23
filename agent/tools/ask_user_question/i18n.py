"""Chinese display text for ``ask_user_question``.

The model always sees the English description and schema (``description.py``);
this is read by the admin tool page only.
"""

from agent.tools.spec import ToolText

ZH_CN = ToolText(
    description=(
        "向用户提出一到三个简短问题并等待回答。当决定确实该由用户来做（两种设计选哪个、"
        "以哪个环境为目标、要不要替换某个东西），而且答案会改变你接下来的做法时使用。"
        "不要用它申请许可：工具调用由客户端确认，不由你确认。一次调用里把需要问的问题都问完"
        "（最多三个），每个问题只用一句话，给出两到三个互斥选项，把推荐项放在第一个并在标签"
        "末尾加 '(Recommended)'。不要添加 'Other' 选项：客户端会给每个问题自动加一个自由填写"
        "的选项。结果是以每个问题 id 为键的 JSON（'{\"answers\": {\"<id>\": {\"answers\": "
        "[...]}}}'）；用户选中的选项以标签形式出现，用户输入的内容作为另一项出现，被跳过的"
        "问题得到空数组。没人回答时 —— 没有客户端连接，或等待超时 —— 答案集为空且结果会说明"
        "原因：用你已有的信息自行决定，说明所做的假设，不要再问一次。"
    ),
    parameters={
        "questions": "要展示给用户的问题。优先 1 个，不要超过 3 个。",
    },
)
