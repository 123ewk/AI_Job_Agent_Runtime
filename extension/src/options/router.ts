// Dashboard 路由（设计权威：前端页面布局 V1.0 §47 页面导航关系）。
// 原理：chrome-extension:// 页面无法使用 HTML5 history 路由，必须 createWebHashHistory；
//       7 个顶级页面 + 默认重定向总览。组件懒加载按需分包。
import { createRouter, createWebHashHistory } from "vue-router"
import type { RouteRecordRaw } from "vue-router"

const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/overview" },
  {
    path: "/overview",
    name: "overview",
    component: () => import("./views/OverviewView.vue"),
    meta: { title: "总览" },
  },
  {
    path: "/conversations",
    name: "conversations",
    component: () => import("./views/ConversationsView.vue"),
    meta: { title: "聊天会话" },
  },
  {
    path: "/jobs",
    name: "jobs",
    component: () => import("./views/JobsView.vue"),
    meta: { title: "岗位管理" },
  },
  {
    path: "/tasks",
    name: "tasks",
    component: () => import("./views/TasksView.vue"),
    meta: { title: "任务中心" },
  },
  {
    path: "/approvals",
    name: "approvals",
    component: () => import("./views/ApprovalsView.vue"),
    meta: { title: "人工确认" },
  },
  {
    path: "/logs",
    name: "logs",
    component: () => import("./views/LogsView.vue"),
    meta: { title: "日志与事件" },
  },
  {
    path: "/settings",
    name: "settings",
    component: () => import("./views/SettingsView.vue"),
    meta: { title: "设置" },
  },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})
