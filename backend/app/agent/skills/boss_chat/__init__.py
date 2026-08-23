"""boss_chat：Boss 直聘 HR 聊天页垂直工具（会话同步 / 消息拉取 / 回复发送）。

skills/ 集中存放未来 agent（doc 06 LangGraph skill_router）可编排的垂直领域工具；
本包自包含，不与 backend 耦合，依赖经 service.BossChatService 构造参数注入。

重命名历史：2026-08-23 由 boss-chat 更名而来（原连字符目录非法包名，无法点号导入）。
现名 boss_chat 为合法包名，可
`from app.agent.skills.boss_chat.service import BossChatService`。
本文件仅作包标记与说明，不在此 re-export（避免与未来 skill_router 接线产生额外耦合面）。
"""
