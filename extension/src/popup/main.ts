import { createApp } from "vue"
import { createPinia } from "pinia"
import Popup from "./Popup.vue"
// 设计 token（样式规范 §51）与 SidePanel 共用，保证扩展内视觉一致
import "../styles/tokens.css"

createApp(Popup).use(createPinia()).mount("#app")
