// ============================================================================
// Boss 直聘 HR 聊天页操作脚本（垂直工具 boss.chat 的浏览器侧）
// ----------------------------------------------------------------------------
// 运行环境：页面 MAIN world。经 chrome_javascript 注入，注入端（toolsHandler.ts
//   toolInjectScript）会把本文件整体包装为 (function(){ <本文件> })() 执行，
//   因此本文件是「函数体」，必须以 return 结尾，返回 JSON 可序列化对象。
//
// 参数注入：Python service 把 __OPERATION__ / __PARAMS__（两个 JSON 字面量）占位符
//   replace 成 json.dumps 后的值，再交给 chrome_javascript。
//   __OPERATION__: "list" | "messages" | "send"
//   __PARAMS__:    { external_id?, text? }（send 时 text 必填）
//
// 约束（对齐 docs/逆向网页分析/BOSS直聘_HR聊天页操作方案_V1.0.md §7 反检测）：
//   - 只读已加载页面（Vue $data / DOM），零新增 zhipin 请求
//   - 不主动点击切换会话、不主动 WebSocket 重连
//   - send 为真实对外写操作，发送决策（approved）由 Python service 侧把关，
//     本脚本只负责「预写 + 派发 Enter」的机械操控
//
// 返回：{ ok, data 按操作而异 }（list: conversations, messages: messages+conversation,
//      send: dispatched/input_cleared/mine），失败 { ok:false, error }
// ============================================================================

const OPERATION = __OPERATION__;   // JSON literal: "list"|"messages"|"send"
const PARAMS = __PARAMS__;          // JSON literal object

// ---------------------------------------------------------------------------
// 工具：取元素干净文本
// ---------------------------------------------------------------------------
function textOf(el) {
  return el ? el.textContent.replace(/\s+/g, " ").trim() : null;
}

// ---------------------------------------------------------------------------
// 工具：从某个候选根元素向上搜含 $data.<key> 的 Vue 组件（Vue2/3 双读兼容）
// ---------------------------------------------------------------------------
function findDataComponent(rootSel, key) {
  const roots = document.querySelectorAll(rootSel);
  for (const el of roots) {
    let node = el.__vue__ || el.__vueParentComponent || null;
    while (node) {
      const d = node.$data || node.data || {};
      if (key in d && d[key]) return node;
      node = node.$parent || node.parent || null;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// list：拉取会话列表
//   主路径 Vue $data.friendList（含 encryptBossId，方案 §1.3「外部ID从 Vue/API 取」）；
//   兜底读 DOM .friend-content（无 external_id，写 warning）。
// ---------------------------------------------------------------------------
function listConversations() {
  const comp = findDataComponent(".friend-content", "friendList");
  if (comp) {
    const list = (comp.$data || comp.data).friendList || [];
    const conversations = list.map((b) => ({
      external_id: b.encryptBossId || null,
      unique_id: b.uniqueId || null,
      friend_id: b.friendId || null,
      encrypt_job_id: b.encryptJobId || null,
      hr_name: b.name || null,
      // company/position 在 friendList 数据里的确切键未在方案§1.3 给出，best-effort
      company: b.brandName || b.bossTitle || null,
      position: b.jobName || null,
      last_msg: b.lastText || null,
      last_time: b.lastTimeValue !== undefined ? String(b.lastTimeValue) : null,
    }));
    return {
      ok: true,
      source: "vue",
      conversations,
      warnings:
        list.length === 0
          ? ["friendList 为空：页面可能未加载完成"]
          : ["Vue friendList 的 company/position 字段为 best-effort 映射，未在方案确认"],
    };
  }

  const conversations = [];
  document.querySelectorAll(".friend-content").forEach((el) => {
    conversations.push({
      external_id: null, // DOM 无加密 ID（方案 §1.3）
      unique_id: null,
      friend_id: null,
      encrypt_job_id: null,
      hr_name: textOf(el.querySelector(".name-text")),
      company: textOf(el.querySelector(".name-box > span:nth-child(2)")),
      position: textOf(el.querySelector(".name-box > span:last-of-type")),
      last_msg: textOf(el.querySelector(".last-msg-text")),
      last_time: textOf(el.querySelector(".time")),
    });
  });
  if (conversations.length === 0) {
    return {
      ok: false,
      error: "未找到会话列表：请确认已登录 Boss 直聘并停留在 HR 聊天页",
      warnings: [],
    };
  }
  return {
    ok: true,
    source: "dom",
    conversations,
    warnings: [
      "DOM 兜底：external_id 需从 Vue friendList 获取，当前 external_id 为 null（无法幂等落库）",
    ],
  };
}

// ---------------------------------------------------------------------------
// messages：拉取当前选中会话的已加载聊天记录（方案 §2.5）
//   会话身份从 Vue $data.boss 取（external_id=encryptBossId）。
//   role: item-friend->hr / item-mine->user（方案 §2.6 枚举映射）。
// ---------------------------------------------------------------------------
function readMessages() {
  const messages = [];
  const items = document.querySelectorAll("li.message-item");
  items.forEach((li) => {
    const role = li.classList.contains("item-mine") ? "user" : "hr";
    messages.push({
      external_msg_id: li.getAttribute("data-mid") || null,
      role,
      content: textOf(li.querySelector(".text-content")),
      sent_at: textOf(li.querySelector(".item-time .time")),
    });
  });
  if (messages.length === 0) {
    return {
      ok: false,
      error: "未找到聊天记录：请确认已登录并选中一个 HR 会话",
      messages: [],
      conversation: null,
      warnings: [],
    };
  }

  const bossComp = findDataComponent("#chat-input, .message-item, .chat-area", "boss");
  const b = bossComp ? (bossComp.$data || bossComp.data).boss : null;
  const conversation = b
    ? {
        external_id: b.encryptBossId || null,
        hr_name: b.name || null,
        encrypt_job_id: b.encryptJobId || null,
        unique_id: b.uniqueId || null,
        friend_id: b.friendId || null,
      }
    : null;
  const warnings = [];
  if (!conversation) warnings.push("未能经 Vue $data.boss 取到会话 external_id（DOM 无加密ID）");
  if (!conversation || !conversation.external_id)
    warnings.push("会话 external_id 缺失：可能无法幂等落库");

  return { ok: true, source: "dom", messages, conversation, warnings };
}

// ---------------------------------------------------------------------------
// send：预写 + 发送（方案 §3.5 方式 A，走页面原生 handleSend）
//   approved 把关在 Python service（这里仅机械操控）。
//   成功判定（§3.5）：① 输入框被清空 ② 出现新 li.message-item.item-mine
//   注意：发送是异步网络操作，item-mine 出现可能滞后；本脚本同步返回当前可见状态，
//         确认成功由后续 messages 复查 state 流转（loading->delivery->read）。
// ---------------------------------------------------------------------------
function sendText(text) {
  if (!text || !text.trim()) return { ok: false, error: "发送文本为空" };
  const input = document.querySelector("#chat-input");
  if (!input) return { ok: false, error: "未找到输入框 #chat-input" };
  input.focus();

  // 1) 预写 + 触发 Vue inputValue 更新（方案 §3.4）
  input.textContent = text;
  input.dispatchEvent(new InputEvent("input", { bubbles: true }));
  input.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
  // IME 编辑结束事件（部分实现需 compositionend 才放开 submit）
  input.dispatchEvent(new CompositionEvent("compositionend", { bubbles: true, data: text }));

  // 2) 确认发送按钮已放开（方案 §3.2 enableSubmit）
  const btn = document.querySelector("button.btn-send");
  if (btn && btn.classList.contains("disabled")) {
    return {
      ok: false,
      dispatched: false,
      reason: "输入事件未生效，发送按钮仍 disabled（可改用 chrome_fill_or_select / chrome_keyboard）",
    };
  }

  // 3) 方式 A：派发 Enter（页面 handleSend 触发，方案 §3.5）
  input.dispatchEvent(
    new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true })
  );

  // 4) 同步成功判定（§3.5 step1/2）
  const inputCleared = (input.textContent || "").trim() === "";
  let mine = null;
  const allMine = document.querySelectorAll("li.message-item.item-mine");
  if (allMine.length) {
    const last = allMine[allMine.length - 1];
    mine = { external_msg_id: last.getAttribute("data-mid"), content: textOf(last.querySelector(".text-content")) };
  }
  return {
    ok: true,
    dispatched: true,
    input_cleared: inputCleared,
    mine,
    warning: mine && !inputCleared ? "input 未清空但已出现 item-mine（发送可能在进行中）" : null,
  };
}

// ---------------------------------------------------------------------------
// 主流程调度
// ---------------------------------------------------------------------------
if (OPERATION === "list") return listConversations();
if (OPERATION === "messages") return readMessages();
if (OPERATION === "send") return sendText(typeof PARAMS === "object" && PARAMS ? PARAMS.text || "" : "");
return { ok: false, error: "未知操作: " + OPERATION };