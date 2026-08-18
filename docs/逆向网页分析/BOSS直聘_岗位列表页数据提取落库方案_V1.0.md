# BOSS直聘 岗位列表页 数据提取与落库方案 V1.0

> 文档类型：逆向网页分析结果（岗位入库管线）
> 分析日期：2026-08-15
> 分析执行：真实浏览器（真人手动打开页面）+ Chrome 扩展 MCP 通道（browser-mcp-lite，无 CDP 调试会话）
> 所属项目：AI 求职 Agent（Chrome Extension + FastAPI 后端）
> 适用分支：`feature/phase2-backend-api-v2`
> 对应需求：`docs/分析需求/BOSS直聘页面信息分析需求_V1.0.md` 第 2 章

---

## 0. 页面访问记录（分析对象）

| 项 | 值 |
|---|---|
| 页面 URL | `https://www.zhipin.com/web/geek/jobs?city=101280100&jobType=1902&query=Python` |
| 页面标题 | `「广州招聘」-2026年广州人才招聘信息 - BOSS直聘` |
| 页面框架 | `zhipin-geek-spa`（Vue2 SPA，webpack 构建，静态资源版本号 `v6719`） |
| 登录态 | 已登录（Cookie 含 `__zp_stoken__`；页面渲染出真实岗位数据） |
| 访问方式 | **真人手动打开**（CDP 主动导航会被 Boss 反自动化检测关闭，已实测确认，见 §7） |
| 本次实例 | 广州 / Python / 岗位类型 1902，列表 15 张卡片 |

**关键结论先行**：本页面为 **CSR（客户端渲染）**，岗位数据由 XHR 拉取后写入 Vue 组件 `$data`。**推荐提取路径：读取已加载页面内存中 Vue 组件的数据（`jobList` 数组），零新增 zhipin 请求、且能拿到明文 `salaryDesc`（绕过反爬字体）。**

---

## 1. 数据来源判定（Q1）

### 1.1 结论：CSR（Vue SPA）

- 页面 body 为 `<div class="page-jobs ...">` 空壳 + 26 个外部 JS（vendor*.js + app*.js），岗位内容全部由前端 JS 渲染。
- 页面加载了 Boss 反自动化检测 SDK：`https://img.bosszhipin.com/static/zhipin/geek/sdk/browser-check-v2.js`（作用见 §7）。
- 无 SSR 内联数据（内联脚本仅埋点/配置，无岗位数据）。

### 1.2 岗位列表 API

| 项 | 值 |
|---|---|
| URL | `https://www.zhipin.com/wapi/zpgeek/search/joblist.json` |
| 形态 | XHR/fetch（`performance.getEntriesByType('resource')` 实测 URL 仅带 `?_=<毫秒时间戳>`，如 `?_=1786773628069`；筛选/分页参数疑似 POST body 或 Cookie 携带，**本次未确认**——见 §9 附录） |
| 响应结构 | `{ code: 0, message, zpData: { hasMore, jobList: [...] } }` |
| 响应键名 | **`zpData.jobList`**（与需求文档 §6 历史线索一致，本次已在 Vue 组件 `$data.jobList` 实测确认） |

> 说明：响应结构从 webpack 模块源码考古确认（`a=c.zpData, this.hasMore=(null==a?void 0:a.hasMore)&&this.isLogin, l=(null==a?void 0:a.jobList)||[]`）。由于我们走「只读」策略，未对 API 重放验证，`code=0` 为成功码为推断（配合 `jobList` 实际渲染成功）。

---

## 2. 岗位卡片 DOM 结构（Q2，实测）

### 2.1 容器层级（实测 class）

```
div.page-jobs
└── div.page-jobs-main
    └── div.job-list-container          ← 列表容器
        └── ul.rec-job-list             ← 列表（本次含 15 个 li）
            └── li.job-card-box         ← 单卡片（旧线索 job-card-wrapper 未命中，当前版本为 job-card-box）
```

- 选择器统计（本次实测命中数）：`job-card` 45 处、`job-card-box` 15 处、`job-info` 15 处、`job-list` 2 处。
- 未命中：`job-card-wrapper`、`job-list-box`、`job-card-box` 的旧版 wrapper 类。

### 2.2 单卡片结构（实测 HTML，含 data-v 属性）

```html
<li data-v-6460f456="" class="job-card-box">
  <div data-v-6460f456="" class="job-info">
    <div data-v-6460f456="" class="job-title clearfix">
      <a data-v-6460f456="" href="/job_detail/7a75cc450a9aebb903152dy1F1pZ.html" class="job-name">python实习生</a>
      <span data-v-6460f456="" class="job-salary">�쌱-�셱元/天</span>   <!-- 反爬字体乱码，见 §2.3 -->
    </div>
    <ul data-v-6460f456="" class="tag-list">
      <li data-v-6460f456="">5天/周</li>
      <li data-v-6460f456="">3个月</li>
      <li data-v-6460f456="">本科</li>
    </ul>
  </div>
  <div data-v-6460f456="" class="job-card-footer">
    <a data-v-6460f456="" href="/gongsi/39a252d6c6b734351HRy0tS6GA~~.html?from=top-card" ka="company_logo_click_..." class="boss-info">
      <div data-v-6460f456="" class="boss-logo"><img src="https://img.bosszhipin.com/..._s.jpg"></div>
      <span data-v-6460f456="" class="boss-name">讯南科技</span>
    </a>
    <span data-v-6460f456="" class="company-location"> 广州·海珠区·琶洲 </span>
  </div>
</li>
```

### 2.3 各字段定位方式

| 字段 | CSS 选择器（卡片内） | 实测示例 |
|---|---|---|
| 职位标题 | `a.job-name` | `python实习生` |
| 薪资（DOM 文本） | `span.job-salary` | `�쌱-�셱元/天`（**反爬字体乱码**，勿从 DOM 取） |
| 薪资（明文） | **Vue `$data` 的 `salaryDesc`** | `120-180元/天`（见 §3.2） |
| 公司名称 | `a.boss-info .boss-name` | `讯南科技` |
| 工作地点 | `span.company-location` | `广州·海珠区·琶洲` |
| 职位详情链接 | `a.job-name` 的 href | `/job_detail/7a75cc450a9aebb903152dy1F1pZ.html` |
| 标签/福利 | `ul.tag-list > li` | `5天/周`、`3个月`、`本科` |

---

## 3. external_id 提取（Q3，实测）

### 3.1 位置

**`encryptJobId`** —— 同时出现在：
1. 卡片标题链接 URL：`/job_detail/{encryptJobId}.html`（如 `https://www.zhipin.com/job_detail/7a75cc450a9aebb903152dy1F1pZ.html`）
2. Vue 组件 `$data.jobList[i].encryptJobId`（与 URL 中一致）

### 3.2 实测示例（5 条）

| encryptJobId（external_id） | jobName | salaryDesc（明文） |
|---|---|---|
| `7a75cc450a9aebb903152dy1F1pZ` | python实习生 | 120-180元/天 |
| `1d70ceecf352e86d0nJ82NS7EVZV` | AIAgent应用实习生 | 100-130元/天 |
| `2e1896be6d5a904f0nBz39u9E1JR` | python开发实习生 | 140-160元/天 |
| `cf0452259b8685ca0nF929W1ElJS` | Python后端开发实习生-可转正 | 100-130元/天 |
| `cdc5d6d7d37721e90nV929W7FlpS` | （第 5 条） | - |

> **重要**：`encryptJobId` 为**混合字符编码**（含数字/小写字母/`~`，非纯数字），≤100 字符，可直接作后端 `external_id`（去重锚点）。旧线索「纯数字 ID」不成立。

---

## 4. 分页 / 滚动加载机制（Q4，实测）

- **无限滚动（懒加载）**，无翻页按钮。
- 数据模型：`pageVo: { page: 1, pageSize: 15 }`（webpack 考古确认），每次加载 **15 条**。
- 控制标志：响应 `zpData.hasMore`（`this.hasMore = zpData.hasMore && this.isLogin`）。
- 滚动到底部（页面 body 滚动容器）触发下一次 `search/joblist.json` 请求（本次已观察到 3 次 joblist 请求，间隔对应滚动）。
- 加载更多请求形态：同 `search/joblist.json`，页码参数位置**未确认**（推断在 POST body 或 Cookie，见 §9）。

---

## 5. 岗位详情页（Q5，部分未确认）

| 项 | 状态 |
|---|---|
| 详情 URL 模式 | 已确认：`https://www.zhipin.com/job_detail/{encryptJobId}.html` |
| 详情 API | 已观察到：`/wapi/zpgeek/job/detail.json?securityId={...}`（`securityId` 来自列表数据；本次未重放验证） |
| `description` DOM 位置 | **未确认**（未打开详情页；列表数据无 description 字段） |
| 落库建议 | 后端 `description` 允许 null → **首版仅落列表字段、description 留空**，详情抓取后续单独分析 |

---

## 6. 字段映射表（页面/Vue 数据 → JobCreate）

> 端点：`POST /api/v1/jobs`（幂等去重：同 `(platform, external_id)` 静默返回已有记录）。

| JobCreate 字段 | 类型/约束 | 页面来源 | 提取方式 | 实测示例 |
|---|---|---|---|---|
| `platform` | string ≤30，默认 "boss" | 固定 | 常量 | `boss` |
| `external_id` | **必填** ≤100 | `jobList[i].encryptJobId` | Vue `$data` | `7a75cc450a9aebb903152dy1F1pZ` |
| `title` | string\|null ≤300 | `jobList[i].jobName` | Vue `$data` | `python实习生` |
| `company` | string\|null ≤200 | `jobList[i].brandName` | Vue `$data` | `讯南科技` |
| `salary` | string\|null ≤100 | `jobList[i].salaryDesc` | Vue `$data`（**明文**） | `120-180元/天` |
| `location` | string\|null ≤200 | `${cityName}·${areaDistrict}·${businessDistrict}` | Vue `$data` 拼接 | `广州·海珠区·琶洲` |
| `description` | string\|null | 详情页 | 未确认，留空 | `null` |
| `source_url` | string\|null ≤500 | `/job_detail/{encryptJobId}.html` | 拼接 | `https://www.zhipin.com/job_detail/7a75cc...html` |
| `hr_id` | int\|null | 关联 HR（可选） | `encryptBossId` → HR 落库后回填 | - |

### 6.1 Vue 数据中可用的额外字段（附赠，按需取用）

`securityId`（详情 API 参数）、`lid`、`bossName`、`bossTitle`、`encryptBossId`（HR external_id）、`encryptBrandId`（公司 external_id）、`brandIndustry`、`brandScaleName`、`brandStageName`、`welfareList`、`jobLabels`、`skills`、`jobExperience`、`jobDegree`、`daysPerWeekDesc`、`leastMonthDesc`、`cityName`、`areaDistrict`、`businessDistrict`、`jobType`、`proxyJob`、`anonymous`、`gps` 等（单条 48 字段）。

---

## 7. 推荐提取方案与伪代码

### 7.1 方案 A：读取 Vue 组件数据（推荐）

**原理**：岗位数据已由页面自身加载进 Vue 组件 `$data.jobList`（明文），从**已加载页面内存**读取，**零新增 zhipin 请求**，符合 §8 红线。

**提取步骤**：
1. 定位任意卡片元素 `li.job-card-box`；
2. 通过 `el.__vue__` / `__vueParentComponent` 找到 Vue 组件树，递归找到含 `$data.jobList`（数组且长度>0）的组件；
3. 读取 `jobList[i]` 各字段 → 映射 §6 表；
4. 每张卡片 `POST /api/v1/jobs`（幂等）。

**伪代码**：

```js
// 运行于 zhipin 岗位页（扩展 content script / inject_script，MAIN world）
function extractJobList() {
  // 1. 找含 jobList 的 Vue 组件（页面已渲染的数据，非新请求）
  let target = null;
  document.querySelectorAll('li.job-card-box').forEach(el => {
    if (target) return;
    const v = el.__vue__ || el.__vueParentComponent;
    let node = v;
    while (node && !target) {
      if (node.$data && Array.isArray(node.$data.jobList) && node.$data.jobList.length) target = node;
      node = node.$parent || (node.$root && node.$root.$children ? null : null);
    }
  });
  if (!target) return { ok: false, reason: 'jobList 组件未找到（页面未加载完成或未登录）' };
  return target.$data.jobList.map(j => ({
    platform: 'boss',
    external_id: j.encryptJobId,
    title: j.jobName,
    company: j.brandName,
    salary: j.salaryDesc,                       // 明文，绕过反爬字体
    location: [j.cityName, j.areaDistrict, j.businessDistrict].filter(Boolean).join('·'),
    source_url: `https://www.zhipin.com/job_detail/${j.encryptJobId}.html`,
    // 附赠（按需）：
    _hr_external_id: j.encryptBossId,
    _brand_external_id: j.encryptBrandId,
    _securityId: j.securityId,
    _lid: j.lid,
  }));
}
// 落库：对每条 POST /api/v1/jobs（后端幂等去重）
```

**可靠性**：✅ 实测可用（本次已从页面成功提取 15 条明文数据）；依赖 Vue 生产实例保留 `$data`（Vue2 生产模式保留，Boss 未混淆组件数据）。
**反检测风险**：✅ 最低（零新增请求、只读内存）。

### 7.2 方案 B：API 监听/重放（备选，风险较高）

**原理**：拦截/读取已发生的 `search/joblist.json` 响应 JSON，或重放请求。
- 读取已发生响应：需在页面加载早期挂 `performance` 或 fetch 钩子（埋点式），本次只读到 URL 拿不到响应体。
- 重放请求：会**产生新的 zhipin 请求**，且分页参数位置未确认（§9），还可能触发 security-check —— **不推荐**。

**结论**：落库以**方案 A** 为准；方案 B 仅作长期备选，需先补齐请求参数逆向。

---

## 8. 反检测注意事项

1. **红线（本项目 V2.0）**：content script 禁止 DOM 数据抽取，岗位/聊天数据一律经 **Skill → MCP 同步通道**落库。本文档方案即按此设计（扩展/inject_script 侧提取 → 交给 Skill 汇总 → POST 后端）。
2. **必须由真人手动打开页面**：任何 CDP/Playwright 驱动的主动导航到 zhipin 会被检测并关闭页面（console 报 `Scripts may close only the windows that were opened by them` 或导航回退）。本次实测：browser-use（CDP 挂载）三次导航均被杀；扩展通道 + 真人打开则完全正常。
3. **只读策略**：分析/提取过程不发起任何新的 zhipin 请求（含 XHR、`window.open`、页面跳转）。滚动加载新页 = 真人滚动。
4. **反爬字体**：`kanzhun-mix`（`span.job-salary` font-family）会把数字渲染成 PUA 私有区字符，**DOM 文本不可直接入库**；必须走 Vue `$data.salaryDesc`（明文）或后续做字体映射。
5. **其他特征**：`browser-check-v2.js` 为 Boss 浏览器指纹检测 SDK；`security-check` / `verify-slider` 滑块可能出现（本次未触发）；频繁 API 重放有 IP 封禁风险。
6. **扩展通道选型**：选用 **browser-mcp-lite**（MV3 扩展 + WebSocket + 页面内 `chrome.scripting`，**无 `chrome.debugger`/CDP 会话**），页面内操作无调试器痕迹；扩展权限仅 `tabs/activeTab/scripting/alarms/storage`，源码 ~500 行可审计。

---

## 9. 附录：其他发现与未确认项

### 9.1 已确认

- 页面框架：`zhipin-geek-spa`，静态资源版本 `v6719`（`staticPath` 内联变量，会随版本变化）。
- 埋点 SDK：`ka.v1.min.js`、`patas.2.3.0.min.js`、`warlockdata`、`boss-analytics`（`BossAnalytics` 全局）。
- 登录态 Cookie：`__zp_stoken__`（值被 URL 编码，敏感勿外泄）、`__a`、`__c`、`__l`、`ab_guid`、`isOHPC`。
- 附加 API 观察（页面加载时已发生）：`/wapi/zpCommon/toggle/all`、`/wapi/zpgeek/search/job/seo/data.json`、`/wapi/zpgeek/search/job/tdk.json`、`/wapi/zpgeek/job/detail.json?securityId=...`（详情，含 `lid`）。

### 9.2 未确认（标注，勿臆造）

- `search/joblist.json` 的**请求方法与分页参数位置**（URL 仅见 `?_=` 时间戳；疑 POST body 或 Cookie 携带 `page/pageSize/query/city/jobType`）。→ 若要走方案 B，需先确认。
- `description` 在详情页的 DOM 位置（未打开详情页）。
- 本次 URL 未出现 `_security_check` 参数（需求文档 §6 线索）；该参数是否与登录态/时段相关，未确认。
- 详情 API `detail.json` 的请求参数组合（`securityId`+`lid` 疑似，未重放验证）。
- 大量岗位数据是否受「未登录只显示部分」影响（本页 15 条全量渲染，`hasMore` 依赖 `isLogin`）。

### 9.3 后续建议

1. 聊天页分析（`/web/geek/chat`）独立进行，产出 `文档2：HR聊天页操作方案`。
2. 若要增强 `description`，可单独对详情页 `job/detail.json` 做一次只读分析（用户手动打开单条详情页后读取）。
