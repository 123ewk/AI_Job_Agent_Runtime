import { createApp } from "vue"
import { createPinia } from "pinia"
import App from "./App.vue"
// 设计 token 与 SidePanel 共用，保证扩展内视觉一致
import "../styles/tokens.css"

createApp(App).use(createPinia()).mount("#app")
