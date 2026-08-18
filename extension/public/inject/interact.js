// Interact helpers —— 页面 MAIN world 交互脚本。
//
// 由扩展 background toolsHandler 按需注入（chrome.scripting.executeScript, files）。
// 注入后定义 window.__mcpInteract，供 click/fill/keyboard 等调用。
// 幂等：重复注入只覆盖定义，无副作用。
//
// 设计约束：
//   - MAIN world（与页面共享 JS 上下文），可读取 Vue2 $data 等页面内部状态。
//   - 不建立 CDP 调试会话 —— 这是绕过 BOSS 直聘反自动化检测的关键。
//   - 交互路径带拟人节奏（随机 30~150ms 延迟），避免机械化操作特征。
//   - 所有方法返回 JSON 可序列化对象 { ok, ... } / { ok:false, error }。
(() => {
  if (window.__mcpInteract) return; // 已注入，跳过

  // --- 工具函数 ---
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const jitter = () => sleep(30 + Math.floor(Math.random() * 120));
  const err = (error) => ({ ok: false, error: String(error) });
  const ok = (data) => ({ ok: true, ...data });

  /** 按 ref_* 句柄反查元素（ref 由 accessibility-tree.js 写入 window.__mcpRefMap）。 */
  function resolveRef(ref) {
    const map = window.__mcpRefMap;
    if (!map || typeof map.get !== "function") return null;
    for (const [el, r] of map.entries()) {
      if (r === ref) return el;
    }
    return null;
  }

  /** 解析目标元素：ref 优先，其次 CSS selector，最后坐标。 */
  function resolveElement({ ref, selector, x, y }) {
    if (ref) {
      const el = resolveRef(ref);
      if (el) return el;
      throw new Error(`ref 不存在或已失效: ${ref}（页面可能已变化，请重新 chrome_read_page）`);
    }
    if (selector) {
      const el = document.querySelector(selector);
      if (el) return el;
      throw new Error(`selector 未匹配到元素: ${selector}`);
    }
    if (x != null && y != null) {
      const el = document.elementFromPoint(x, y);
      if (el) return el;
      throw new Error(`坐标 (${x},${y}) 处无元素`);
    }
    throw new Error("必须提供 ref / selector / (x,y) 之一");
  }

  function fire(el, type, init = {}) {
    const evt = new MouseEvent(type, {
      bubbles: true,
      cancelable: true,
      view: window,
      ...init,
    });
    el.dispatchEvent(evt);
  }

  // --- 点击 ---
  async function click(params = {}) {
    try {
      const el = resolveElement(params);
      await jitter();
      el.scrollIntoView({ block: "center", behavior: "instant" });
      await sleep(40);
      // 完整事件序列（部分 Vue 组件监听 mousedown / mouseup）
      fire(el, "mousemove");
      fire(el, "mouseover");
      fire(el, "mousedown", { button: 0 });
      fire(el, "mouseup", { button: 0 });
      fire(el, "click", { button: 0 });
      return ok({ tag: el.tagName, text: (el.textContent || "").trim().slice(0, 80) });
    } catch (e) {
      return err(e);
    }
  }

  // --- 填充（contenteditable / input / textarea）---
  async function fill(params = {}) {
    try {
      const { value } = params;
      if (typeof value !== "string") throw new Error("value 必须为字符串");
      const el = resolveElement(params);
      await jitter();
      el.focus();
      await sleep(30);

      if (el.isContentEditable) {
        el.textContent = value;
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      } else if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
        // 走原生 setter，确保 Vue/React 能感知值变化
        const proto = el instanceof HTMLInputElement ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
        Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      } else {
        throw new Error(`不支持的目标元素类型: ${el.tagName}`);
      }
      return ok({ tag: el.tagName, length: value.length });
    } catch (e) {
      return err(e);
    }
  }

  // --- 键盘（按键 + 修饰键，作用于当前焦点元素）---
  async function keyboard(params = {}) {
    try {
      const key = params.key;
      if (!key) throw new Error("key 必填");
      const modifiers = (params.modifiers || []).map((m) => m.toLowerCase());
      const active = document.activeElement || document.body;
      await jitter();

      const modFlags = {
        ctrlKey: modifiers.includes("ctrl"),
        shiftKey: modifiers.includes("shift"),
        altKey: modifiers.includes("alt"),
        metaKey: modifiers.includes("meta"),
      };
      const init = { bubbles: true, cancelable: true, view: window, ...modFlags };
      active.dispatchEvent(new KeyboardEvent("keydown", { key, ...init }));
      if (key.length === 1) {
        active.dispatchEvent(new KeyboardEvent("keypress", { key, ...init }));
      }
      active.dispatchEvent(new KeyboardEvent("keyup", { key, ...init }));
      return ok({ key, modifiers, target: active.tagName });
    } catch (e) {
      return err(e);
    }
  }

  // --- 读取正文（文本 + HTML，供 get_web_content 使用）---
  function getWebContent() {
    try {
      return ok({
        title: document.title,
        url: location.href,
        text: (document.body ? document.body.innerText : "").slice(0, 200_000),
        html: (document.body ? document.body.outerHTML : "").slice(0, 500_000),
      });
    } catch (e) {
      return err(e);
    }
  }

  // --- 页内导航（location.href 赋值；非 CDP 导航，不触发反自动化检测）---
  function navigate(params = {}) {
    try {
      const { url } = params;
      if (!url) throw new Error("url 必填");
      const target = new URL(url, location.href).href;
      // 延迟一拍让 executeScript 先拿到返回值，再触发导航
      setTimeout(() => { location.href = target; }, 50);
      return ok({ navigating: true, url: target });
    } catch (e) {
      return err(e);
    }
  }

  // --- 拦截后续弹窗（alert/confirm/prompt 自动应答）---
  function handleDialog(params = {}) {
    try {
      const accept = params.accept !== false;
      const text = params.text || "";
      window.alert = () => {};
      window.confirm = () => accept;
      window.prompt = () => (accept ? text : null);
      return ok({ patched: true, accept, text });
    } catch (e) {
      return err(e);
    }
  }

  window.__mcpInteract = { click, fill, keyboard, getWebContent, navigate, handleDialog };
})();
