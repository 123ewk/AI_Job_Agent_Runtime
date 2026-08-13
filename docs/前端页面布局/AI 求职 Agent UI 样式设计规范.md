# AI 求职 Agent UI 样式设计规范

## 1. 文档概述

### 1.1 设计目标

本 UI 设计以「AI 求职 Agent Chrome Extension」为核心，整体定位为：

> **专业、智能、高效、可信赖的 AI 求职工作台**

界面需要同时满足以下几个目标：

- 让用户能够快速了解 Agent 当前运行状态
- 让用户能够实时看到 AI 正在执行什么操作
- 让用户能够快速处理需要人工确认的事项
- 让用户能够管理职位、聊天、任务和求职流程
- 让复杂的 Agent 工作流程以清晰、低认知负担的方式呈现
- 强调「AI 自动执行 + 人工最终决策」的产品特点

整体视觉风格参考现代 SaaS、AI Agent、开发者工具类产品。

---

# 2. 整体视觉定位

## 2.1 核心关键词

UI 设计围绕以下关键词展开：

**科技感 / AI 感 / 专业 / 简洁 / 高效 / 轻量 / 可信赖**

避免：

- 过度炫酷
- 大量渐变
- 大面积高饱和色
- 复杂动画
- 过度卡片化
- 信息堆叠
- 类似传统后台管理系统的沉重感

---

# 3. 整体页面结构

页面采用典型的三段式工作台布局：

```text
┌────────────────────────────────────────────────────────────┐
│                     顶部导航栏                              │
├───────────────┬──────────────────────────────┬─────────────┤
│               │                              │             │
│               │                              │             │
│   左侧导航     │          主内容区域           │ 右侧辅助区域 │
│               │                              │             │
│               │                              │             │
│               │                              │             │
├───────────────┤                              │             │
│   数据统计     │                              │             │
│               │                              │             │
├───────────────┤                              │             │
│   连接状态     │                              │             │
└───────────────┴──────────────────────────────┴─────────────┘
```

其中：

- **顶部导航栏**：系统级状态和全局操作
- **左侧导航栏**：主要功能模块切换
- **中央区域**：当前页面核心内容
- **右侧区域**：实时事件、人工确认、快捷操作等辅助信息
- **底部左侧**：运行统计和系统连接状态

---

# 4. 页面尺寸规范

## 4.1 推荐基础尺寸

桌面端建议设计基准：

```text
Width: 1440px
Height: 900px
```

同时保证在：

```text
1280 × 720
1366 × 768
1440 × 900
1920 × 1080
```

下能够正常使用。

Chrome Extension 如果采用独立窗口或 Side Panel，则需要额外适配窄屏。

---

# 5. 页面背景

## 5.1 主背景

整体背景使用非常浅的冷灰色：

```css
--bg-page: #F5F7FA;
```

作用：

- 降低白色卡片与背景的视觉冲突
- 提升页面层次
- 避免纯白背景造成刺眼感

---

## 5.2 卡片背景

主要内容卡片：

```css
--bg-card: #FFFFFF;
```

卡片与背景之间主要通过：

- 边框
- 阴影
- 间距

形成层次，而不是依赖明显颜色。

---

# 6. 顶部导航栏

## 6.1 高度

推荐：

```text
Height: 62px
```

顶部导航栏固定在页面顶部。

---

## 6.2 背景

顶部使用深蓝色：

```css
background: #071426;
```

可以使用非常轻微的深蓝渐变：

```css
background: linear-gradient(
  90deg,
  #081526,
  #0D1E34
);
```

不建议使用明显渐变。

---

## 6.3 Logo 区域

左侧：

```text
[AI机器人 Logo] AI 求职 Agent [v1.0.0]
```

推荐：

- Logo：32 × 32px
- 产品名称：18px
- 字重：600
- 版本号：11～12px

版本号采用蓝色胶囊：

```text
┌────────┐
│ v1.0.0  │
└────────┘
```

---

## 6.4 运行状态

顶部中间偏右显示 Agent 当前状态。

示例：

```text
● 运行中   ▼
```

状态颜色：

| 状态 | 颜色 |
|---|---|
| 运行中 | #22C55E |
| 等待确认 | #F59E0B |
| 已暂停 | #64748B |
| 已停止 | #94A3B8 |
| 异常 | #EF4444 |

运行状态使用小圆点：

```css
width: 8px;
height: 8px;
border-radius: 50%;
```

运行状态可以增加非常轻微的呼吸动画。

---

# 7. 自动模式 Switch

顶部提供：

```text
自动模式   [●────]
```

Switch：

- 宽度：44px
- 高度：24px
- 圆角：12px
- 开启：品牌蓝
- 关闭：灰色

开启状态：

```css
background: #1677FF;
```

圆形滑块：

```text
20 × 20px
```

---

# 8. 顶部功能按钮

右侧依次：

```text
通知
设置
更多
最小化
关闭
```

图标建议统一使用：

- Lucide
- Iconify
- Element Plus Icons

不要混用多个 Icon 库。

---

# 9. 左侧导航栏

## 9.1 宽度

推荐：

```text
Width: 232px
```

---

## 9.2 背景

使用深色导航：

```css
background: #081426;
```

与顶部保持统一。

---

## 9.3 导航项目

当前设计包含：

```text
总览
聊天会话
岗位管理
任务中心
人工确认
日志与事件
设置
```

每个导航项：

```text
Height: 48px
Padding: 0 16px
Border-radius: 8px
```

---

## 9.4 默认状态

```text
图标 + 文字
```

颜色：

```css
color: #A9B7CA;
```

---

## 9.5 Hover 状态

鼠标悬停：

```css
background: rgba(255,255,255,0.05);
color: #FFFFFF;
```

---

## 9.6 Active 状态

当前页面使用明显的蓝色背景：

```css
background: #0F4C9B;
color: #FFFFFF;
```

同时可以增加：

```css
box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04);
```

不要使用过于鲜艳的纯蓝。

---

# 10. 导航角标

例如：

```text
聊天会话                 12
人工确认                  3
```

数字角标用于提醒用户存在未处理事项。

普通提醒：

```css
background: #1677FF;
```

高优先级：

```css
background: #F59E0B;
```

危险：

```css
background: #EF4444;
```

角标推荐：

```text
min-width: 20px
height: 20px
border-radius: 10px
font-size: 11px
```

---

# 11. 左侧数据统计区域

导航菜单下面增加：

```text
今日数据
```

用于展示：

- 消息处理
- 发送消息
- 申请投递
- 匹配岗位
- 运行时长

采用深色半透明卡片：

```css
background: rgba(255,255,255,0.05);
```

---

## 11.1 数据数字

主要数字：

```text
24
8
3
12
```

推荐：

```css
font-size: 18px;
font-weight: 600;
color: #FFFFFF;
```

---

## 11.2 数据名称

```css
font-size: 13px;
color: #94A3B8;
```

---

## 11.3 数据分割

每一项之间使用非常浅的分割线：

```css
border-bottom: 1px solid rgba(255,255,255,0.06);
```

---

# 12. 左下角系统连接状态

显示：

```text
● 已连接后端

ws://localhost:8000
```

状态点使用绿色。

文字：

```css
font-size: 12px;
color: #CBD5E1;
```

连接地址：

```css
font-size: 11px;
color: #64748B;
```

---

# 13. 主内容区域

主内容区域采用：

```text
Padding: 18px
Gap: 16px
```

整体采用 CSS Grid。

推荐：

```css
grid-template-columns: minmax(600px, 1fr) 388px;
```

即：

```text
┌──────────────────────────┬────────────────┐
│                          │                │
│       主内容区域          │    辅助区域     │
│                          │                │
└──────────────────────────┴────────────────┘
```

---

# 14. 卡片设计规范

所有主要内容采用 Card。

## 14.1 圆角

统一：

```css
border-radius: 10px;
```

大型卡片可以：

```text
12px
```

---

## 14.2 边框

推荐：

```css
border: 1px solid #E8EDF3;
```

---

## 14.3 阴影

使用非常弱的阴影：

```css
box-shadow:
  0 2px 8px rgba(15, 23, 42, 0.04);
```

不要使用明显的悬浮阴影。

---

# 15. 卡片标题

统一结构：

```text
标题                         查看全部 >
```

例如：

```text
最近会话                     查看全部 >
```

标题：

```css
font-size: 16px;
font-weight: 600;
color: #111827;
```

辅助操作：

```css
font-size: 13px;
color: #64748B;
```

Hover：

```css
color: #1677FF;
```

---

# 16. Agent 状态卡片

这是首页最重要的视觉模块。

结构：

```text
┌──────────────────────────────────────────┐
│ Agent 状态                运行中         │
│                                          │
│ 当前状态       AI机器人       会话数     │
│ 监听模式                    12个         │
│                                          │
│ 当前任务                    已处理消息    │
│ 监听中 boss.com             24条         │
│                              成功回复率   │
│                              92%          │
└──────────────────────────────────────────┘
```

---

# 17. Agent Logo / Avatar

中心使用机器人形象作为产品核心视觉。

推荐：

```text
96 × 96px
```

外围可以增加淡蓝色光晕。

例如：

```css
box-shadow:
0 0 0 12px rgba(22,119,255,0.05),
0 0 0 24px rgba(22,119,255,0.025);
```

运行状态可以显示动态呼吸效果。

---

# 18. 状态 Badge

例如：

```text
运行中
```

采用绿色浅背景：

```css
background: #ECFDF3;
color: #16A34A;
```

推荐：

```text
padding: 4px 8px;
border-radius: 6px;
font-size: 12px;
```

---

# 19. 成功率数据

例如：

```text
成功回复率
92%
██████████████████
```

进度条：

```text
Height: 4px
Border-radius: 2px
```

完成颜色：

```css
background: #22C55E;
```

---

# 20. 最近会话

最近会话采用列表形式，而不是传统表格。

每条数据：

```text
Logo   公司名称
       最近一条消息
                              时间
                              状态
```

例如：

```text
Huawei   华为技术有限公司
         你好，我们正在寻找AI算法工程师...
                              14:32
                              新消息
```

---

# 21. 会话 Logo

企业 Logo：

```text
40 × 40px
```

圆角：

```text
10px
```

如果没有公司 Logo，使用默认企业图标。

---

# 22. 会话状态标签

### 新消息

绿色：

```css
background: #ECFDF3;
color: #16A34A;
```

### 已回复

蓝色：

```css
background: #EFF6FF;
color: #2563EB;
```

### 已结束

灰色：

```css
background: #F1F5F9;
color: #64748B;
```

---

# 23. 任务进度

任务列表展示 Agent 当前执行情况。

结构：

```text
图标
自动回复 HR 消息
监听并智能回复新消息

24/24
████████████████
完成
```

进度条颜色：

- 完成：绿色
- 执行中：蓝色
- 等待：橙色
- 失败：红色

---

# 24. 实时事件

右侧「实时事件」属于实时监控模块。

推荐使用 Timeline。

结构：

```text
● 14:32   收到华为新消息
│          HR：你好，我们正在寻找...
│
● 14:31   已回复字节跳动HR
│          已发送 2 条消息
│
● 14:28   匹配到新岗位
│          字节跳动 · 25-40K · 北京
```

---

# 25. Timeline 设计

时间使用灰色胶囊：

```text
14:32
```

事件名称：

```css
font-size: 14px;
font-weight: 600;
```

事件描述：

```css
font-size: 12px;
color: #64748B;
```

时间轴：

```css
width: 1px;
background: #E2E8F0;
```

---

# 26. 事件等级

使用不同颜色圆点：

| 类型 | 颜色 |
|---|---|
| 普通操作 | #3B82F6 |
| 成功 | #22C55E |
| 等待确认 | #F59E0B |
| 风险 | #F97316 |
| 错误 | #EF4444 |

---

# 27. 人工确认模块

这是产品非常重要的核心模块。

标题：

```text
人工确认 (3)                     全部 >
```

每个确认事项包含：

```text
图标
事项类型
公司
岗位
具体内容

[拒绝] [通过]
```

例如：

```text
薪资确认
字节跳动 · AI算法工程师
期望薪资：25-35K

[拒绝] [通过]
```

---

# 28. 人工确认按钮

### 拒绝

```css
background: #FFFFFF;
border: 1px solid #EF4444;
color: #EF4444;
```

### 通过

```css
background: #1677FF;
color: #FFFFFF;
```

按钮：

```text
Height: 32px
Padding: 0 14px
Border-radius: 6px
```

通过按钮应当比拒绝按钮更加醒目。

---

# 29. 快捷操作

采用 2 × 3 Grid：

```text
┌──────────┬──────────┐
│ 新建任务  │ 手动同步  │
├──────────┼──────────┤
│ 刷新数据  │ 打开 Boss │
├──────────┼──────────┤
│ 导出日志  │ 设置偏好  │
└──────────┴──────────┘
```

每个操作块：

```text
Height: 78～88px
Border-radius: 10px
Background: #F8FAFC
```

Hover：

```css
background: #F1F5F9;
border-color: #D8E2EE;
```

图标使用 20～22px。

---

# 30. 图标规范

推荐统一使用：

**Lucide Icons**

图标大小：

| 类型 | 尺寸 |
|---|---:|
| 顶部按钮 | 20px |
| 左侧导航 | 19～20px |
| 卡片图标 | 20～24px |
| 状态图标 | 16px |
| 快捷操作 | 22px |

禁止同一页面同时使用：

- Emoji
- SVG 图标
- FontAwesome
- Material Icons
- Lucide

等多套风格。

---

# 31. 字体规范

中文优先：

```css
font-family:
"Inter",
"PingFang SC",
"Hiragino Sans GB",
"Microsoft YaHei",
sans-serif;
```

数字和英文优先使用：

```text
Inter
```

---

# 32. 字号体系

建立统一 Typography Scale：

| 用途 | 字号 | 字重 |
|---|---:|---:|
| 页面主标题 | 20px | 600 |
| Card 标题 | 16px | 600 |
| 普通正文 | 14px | 400 |
| 次级文字 | 13px | 400 |
| 辅助说明 | 12px | 400 |
| Badge | 11～12px | 500 |
| 核心数字 | 20～28px | 600 |
| 超大数据 | 30～36px | 600 |

---

# 33. 主色系统

产品核心色建议采用蓝色。

```css
--primary-50:  #EFF6FF;
--primary-100: #DBEAFE;
--primary-200: #BFDBFE;
--primary-400: #60A5FA;
--primary-500: #3B82F6;
--primary-600: #2563EB;
--primary-700: #1D4ED8;
```

主要按钮推荐：

```css
#1677FF
```

---

# 34. 功能色系统

## Success

```css
#22C55E
```

用于：

- 运行中
- 完成
- 已连接
- 成功
- 已回复

## Warning

```css
#F59E0B
```

用于：

- 等待人工确认
- 风险提示
- 即将超时

## Error

```css
#EF4444
```

用于：

- 任务失败
- 连接异常
- 拒绝
- 高风险操作

## Info

```css
#3B82F6
```

用于：

- 普通提示
- 进行中
- 信息事件

---

# 35. 中性色系统

```css
--text-primary:   #111827;
--text-secondary: #475569;
--text-tertiary:  #64748B;
--text-disabled:  #94A3B8;

--border-light:   #E8EDF3;
--border-default: #D9E2EC;

--bg-page:        #F5F7FA;
--bg-card:        #FFFFFF;
--bg-secondary:   #F8FAFC;
```

---

# 36. 间距系统

统一采用 4px 基础间距：

```text
4
8
12
16
20
24
32
40
48
```

推荐：

- 页面 Padding：20px
- Card Padding：20px
- Card 间距：16px
- 标题与内容：16px
- 列表项间距：12～16px
- 图标与文字：8px

---

# 37. 按钮规范

## Primary

```text
蓝色背景
白色文字
```

用于：

- 通过
- 保存
- 开始任务
- 确认

---

## Secondary

```text
白色背景
灰色边框
深色文字
```

用于：

- 取消
- 返回
- 查看详情

---

## Danger

```text
白色背景
红色边框
红色文字
```

用于：

- 删除
- 拒绝
- 停止任务

---

# 38. 输入框

输入框高度：

```text
36～40px
```

默认：

```css
border: 1px solid #D9E2EC;
border-radius: 7px;
```

Focus：

```css
border-color: #1677FF;
box-shadow: 0 0 0 3px rgba(22,119,255,0.10);
```

---

# 39. 下拉菜单

顶部运行状态下拉菜单、设置选项等统一采用：

```text
background: #FFFFFF
border: 1px solid #E8EDF3
border-radius: 8px
box-shadow: 0 8px 24px rgba(15,23,42,0.10)
```

菜单项高度：

```text
36～40px
```

---

# 40. 状态体系

Agent 产品必须建立完整的状态视觉语言。

```text
运行中
   ↓
执行任务
   ↓
等待确认
   ↓
继续执行
   ↓
完成
```

异常：

```text
执行中
  ↓
失败
  ↓
重试 / 停止
```

视觉必须让用户一眼判断 Agent 当前处于什么状态。

---

# 41. 加载状态

禁止页面出现长时间空白。

使用：

- Skeleton
- Spinner
- Progress
- Shimmer

例如任务列表加载：

```text
████████████
████████
██████████████
```

---

# 42. 动画规范

整体动画需要克制。

推荐：

```text
Duration: 150～250ms
Easing: ease-out
```

适合：

- Hover
- Button
- Card
- Dropdown
- Modal
- Sidebar

Agent 状态动画：

```text
1.5～2.0s
```

例如运行中的绿色状态点进行轻微呼吸。

禁止：

- 大幅弹跳
- 高频闪烁
- 连续旋转
- 大面积粒子动画

---

# 43. 阴影层级

建立三个层级。

### Level 1

普通 Card：

```css
0 2px 8px rgba(15,23,42,.04)
```

### Level 2

Dropdown：

```css
0 8px 24px rgba(15,23,42,.10)
```

### Level 3

Modal：

```css
0 16px 48px rgba(15,23,42,.16)
```

---

# 44. 弹窗设计

人工确认弹窗应该是产品重点。

结构：

```text
┌─────────────────────────────┐
│ 薪资确认              ×      │
├─────────────────────────────┤
│                             │
│ 字节跳动                     │
│ AI算法工程师                 │
│                             │
│ HR：                         │
│ 你的期望薪资是多少？          │
│                             │
│ Agent建议                    │
│ 25-35K                       │
│                             │
│     [取消]       [确认]       │
└─────────────────────────────┘
```

Modal 宽度：

```text
480～560px
```

---

# 45. Toast

成功：

```text
✓ 任务创建成功
```

警告：

```text
! Agent 正在等待人工确认
```

错误：

```text
× 消息发送失败
```

位置建议：

```text
右上角
```

持续时间：

```text
2～4 秒
```

---

# 46. 响应式布局

当宽度缩小时：

### ≥ 1400px

完整三栏结构：

```text
Sidebar + Main + Right Panel
```

### 1200～1400px

右侧区域缩小。

### 1000～1200px

右侧辅助区域可以折叠。

### < 1000px

主区域：

```text
Sidebar + Main
```

实时事件、人工确认等改为抽屉。

---

# 47. Chrome Extension 窄屏模式

如果产品运行在 Chrome Side Panel 中，应提供专门布局。

推荐：

```text
Width: 360～480px
```

此时：

```text
顶部 Header
↓
Agent 状态
↓
人工确认
↓
实时事件
↓
任务进度
```

隐藏：

- 左侧完整 Sidebar
- 大型数据统计
- 次要信息

使用底部 Tab：

```text
总览 | 会话 | 岗位 | 任务 | 设置
```

---

# 48. 深色模式

产品可以支持 Dark Mode，但不建议第一版本优先开发。

深色模式：

```css
--bg-page: #0B1120;
--bg-card: #111827;
--bg-secondary: #172033;

--text-primary: #F8FAFC;
--text-secondary: #CBD5E1;

--border-light: #1E293B;
```

蓝色品牌色保持不变。

---

# 49. 可访问性

必须保证：

- 文本与背景具有足够对比度
- 不能只通过颜色表达状态
- 按钮必须有明确文字或 aria-label
- 所有交互元素支持键盘操作
- Focus 状态清晰
- Tooltip 提供图标含义
- 错误信息不能只显示红色

例如：

```text
● 运行中
```

不能只有绿色圆点，还必须存在「运行中」文字。

---

# 50. UI 设计原则

整个项目遵循以下原则：

### 原则一：信息优先

用户打开插件后，第一眼应该知道：

```text
Agent 是否运行
正在做什么
有没有需要我处理的事情
今天完成了多少任务
```

---

### 原则二：AI 操作透明

Agent 不是黑盒。

用户应该能够看到：

```text
发现岗位
↓
匹配岗位
↓
进入聊天
↓
读取 HR 消息
↓
AI 分析
↓
生成回复
↓
发送消息
↓
等待下一步
```

---

### 原则三：人工确认突出

涉及：

- 薪资
- 工作地点
- 加班
- 外包
- 试用期
- 是否接受岗位
- 是否发送简历

等高影响决策时，应突出人工确认。

---

### 原则四：状态颜色统一

整个项目不得出现：

```text
A 页面绿色 = 成功
B 页面绿色 = 运行中
C 页面绿色 = 普通信息
```

必须建立统一 Design Token。

---

# 51. 推荐 CSS Token

实际开发建议统一建立：

```css
:root {
  --color-primary: #1677FF;

  --color-success: #22C55E;
  --color-warning: #F59E0B;
  --color-danger: #EF4444;
  --color-info: #3B82F6;

  --color-bg-page: #F5F7FA;
  --color-bg-card: #FFFFFF;
  --color-bg-secondary: #F8FAFC;

  --color-text-primary: #111827;
  --color-text-secondary: #475569;
  --color-text-tertiary: #64748B;
  --color-text-disabled: #94A3B8;

  --color-border: #E8EDF3;

  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;

  --spacing-1: 4px;
  --spacing-2: 8px;
  --spacing-3: 12px;
  --spacing-4: 16px;
  --spacing-5: 20px;
  --spacing-6: 24px;
  --spacing-8: 32px;

  --shadow-card:
    0 2px 8px rgba(15, 23, 42, 0.04);

  --shadow-dropdown:
    0 8px 24px rgba(15, 23, 42, 0.10);

  --transition-fast: 150ms ease;
  --transition-normal: 200ms ease;
}
```

---

# 52. Vue 3 组件设计建议

如果采用 Vue 3 + Composition API，建议将 UI 拆成：

```text
components/
├── layout/
│   ├── AppHeader.vue
│   ├── AppSidebar.vue
│   ├── AppMain.vue
│   └── AppRightPanel.vue
│
├── dashboard/
│   ├── AgentStatusCard.vue
│   ├── TodayStats.vue
│   ├── RecentSessions.vue
│   ├── TaskProgress.vue
│   ├── RealtimeEvents.vue
│   ├── HumanConfirmations.vue
│   └── QuickActions.vue
│
├── common/
│   ├── StatusBadge.vue
│   ├── ProgressBar.vue
│   ├── CompanyAvatar.vue
│   ├── EmptyState.vue
│   ├── LoadingState.vue
│   ├── ConfirmModal.vue
│   └── Toast.vue
```

---

# 53. 页面视觉层级

首页必须形成明显的视觉优先级：

```text
第一优先级
Agent 当前状态
        ↓
第二优先级
人工确认 / 实时事件
        ↓
第三优先级
最近会话 / 当前任务
        ↓
第四优先级
快捷操作 / 统计数据
```

因此不要让所有 Card 使用完全相同的视觉重量。

---

# 54. 最终设计风格总结

最终 UI 应呈现：

```text
深色科技感导航
        +
白色轻量化内容卡片
        +
蓝色 AI 品牌色
        +
绿色运行状态
        +
橙色人工确认
        +
红色风险提示
        +
大量留白
        +
轻边框
        +
弱阴影
        +
细腻微动画
```

最终视觉效果应该接近：

> **AI Agent 控制台 + 求职工作台 + 现代 SaaS Dashboard**

而不是传统的：

> **企业后台管理系统 / 数据管理平台**

最重要的设计原则是：

**让用户感觉「AI 正在帮我工作」，而不是「我正在操作一个复杂的后台系统」。**