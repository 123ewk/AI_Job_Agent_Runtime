// Dashboard 管理控制台入口（options_ui，open_in_tab 全标签打开，1280×800 基准）。
// 职责：挂载路由 + Pinia + Dashboard 布局。router 仅此入口使用（SidePanel/Popup 无 router）。
import { createApp } from "vue"
import { createPinia } from "pinia"
import App from "./App.vue"
import { router } from "./router"
// 设计 token（样式规范 §51）全局引入，供所有 SFC scoped style 消费
import "../styles/tokens.css"

createApp(App).use(createPinia()).use(router).mount("#app")
