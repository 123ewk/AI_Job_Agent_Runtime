// ============================================================================
// Boss 直聘岗位列表页提取脚本（垂直工具 boss.extract_jobs 的浏览器侧）
// ----------------------------------------------------------------------------
// 运行环境：页面 MAIN world。经 chrome_javascript 注入，注入端（toolsHandler.ts
//   toolInjectScript）会把本文件整体包装为 (function(){ <本文件> })() 执行，
//   因此本文件是「函数体」，必须以 return 结尾，返回 JSON 可序列化对象。
//
// 约束（对齐 docs/逆向网页分析/BOSS直聘_岗位列表页数据提取落库方案_V1.0.md §8）：
//   - 只读已加载页面（Vue $data / DOM），零新增 zhipin 请求
//   - 不触发点击/滚动，页面滚到哪读到哪
//
// 返回：{ ok, jobs: [...], source: "vue"|"dom", warnings: [...] }
//   jobs[] 字段映射见方案 §6：external_id=encryptJobId（必填）、title=jobName、
//   company=brandName、salary=salaryDesc（明文）、location=城市·区·商圈、
//   source_url=job_detail/{encryptJobId}.html、welfare_list/tags 供筛选。
// ============================================================================

const CARD_SELECTOR = "li.job-card-box";

// ---------------------------------------------------------------------------
// 1) 主路径：从 Vue 组件树找含 $data.jobList 的组件
//    Boss 是 Vue2 SPA（zhipin-geek-spa），岗位数据已在页面内存中以明文存在。
//    兼容 Vue3：node.$data / node.data 与 node.$parent / node.parent 双读。
// ---------------------------------------------------------------------------
function findJobListComponent() {
  const cards = document.querySelectorAll(CARD_SELECTOR);
  for (const el of cards) {
    let node = el.__vue__ || el.__vueParentComponent || null;
    while (node) {
      const data = node.$data || node.data || {};
      if (Array.isArray(data.jobList) && data.jobList.length > 0) return node;
      node = node.$parent || node.parent || null;
    }
  }
  return null;
}

function mapVueJob(j) {
  return {
    external_id: j.encryptJobId || null,
    title: j.jobName || null,
    company: j.brandName || null,
    salary: j.salaryDesc || null,
    location: [j.cityName, j.areaDistrict, j.businessDistrict].filter(Boolean).join("·") || null,
    source_url: j.encryptJobId
      ? "https://www.zhipin.com/job_detail/" + j.encryptJobId + ".html"
      : null,
    welfare_list: Array.isArray(j.welfareList) ? j.welfareList : [],
    tags: Array.isArray(j.jobLabels) ? j.jobLabels : [],
  };
}

// ---------------------------------------------------------------------------
// 2) 兜底：Vue 不可用时解析卡片 DOM
//    注意：DOM 文本薪资为反爬混淆字体（kanzhun-mix），一律置空不入库。
// ---------------------------------------------------------------------------
function extractFromDom() {
  const jobs = [];
  document.querySelectorAll(CARD_SELECTOR).forEach((card) => {
    const nameEl = card.querySelector("a.job-name");
    const href = (nameEl && nameEl.getAttribute("href")) || "";
    const m = href.match(/\/job_detail\/([^.]+)\.html/);
    const external_id = m ? m[1] : null;
    if (!external_id) return; // 无外键无法幂等落库，跳过
    const companyEl = card.querySelector("a.boss-info .boss-name");
    const locEl = card.querySelector("span.company-location");
    const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : null);
    jobs.push({
      external_id,
      title: text(nameEl),
      company: text(companyEl),
      salary: null, // 反爬字体，置空
      location: text(locEl),
      source_url: href ? "https://www.zhipin.com" + href : null,
      welfare_list: [],
      tags: [],
    });
  });
  return jobs;
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------
const comp = findJobListComponent();
if (comp) {
  const raw = (comp.$data || comp.data || {}).jobList || [];
  const jobs = raw.map(mapVueJob).filter((j) => j.external_id);
  return {
    ok: true,
    jobs,
    source: "vue",
    warnings: raw.length === 0 ? ["jobList 为空：页面可能未加载完成"] : [],
  };
}

const domJobs = extractFromDom();
if (domJobs.length > 0) {
  return {
    ok: true,
    jobs: domJobs,
    source: "dom",
    warnings: ["Vue jobList 不可用，已用 DOM 兜底：salary 置空（反爬字体），welfare/tags 缺失"],
  };
}

return {
  ok: false,
  error: "未找到岗位卡片：请确认已登录 Boss 直聘并停留在岗位列表页",
  jobs: [],
  warnings: [],
};
