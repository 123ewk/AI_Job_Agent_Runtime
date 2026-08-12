import { createApp } from "vue"
import { createPinia } from "pinia"
import AppShell from "./AppShell.vue"
// 设计 token（doc 12 §4.1）全局引入，供所有 SFC scoped style 消费
import "../styles/tokens.css"

createApp(AppShell).use(createPinia()).mount("#app")
