import { createApp } from "vue"
import { createPinia } from "pinia"
import SidePanel from "./SidePanel.vue"
// 设计 token（样式规范 §51）全局引入，供所有 SFC scoped style 消费
import "../styles/tokens.css"

createApp(SidePanel).use(createPinia()).mount("#app")
