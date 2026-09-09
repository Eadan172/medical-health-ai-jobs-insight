# 医药健康+AI岗位洞察平台

[![Website](https://img.shields.io/badge/Website-Live-blue)](https://fpbec7iecuz4g.ok.kimi.link)
[![React](https://img.shields.io/badge/React-18.2.0-61DAFB?logo=react)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0.0-3178C6?logo=typescript)](https://www.typescriptlang.org/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS-3.4.19-06B6D4?logo=tailwindcss)](https://tailwindcss.com/)

> 实时聚合51job、Boss直聘、猎聘网数据，解码医药健康+AI行业人才趋势

![Platform Preview](https://via.placeholder.com/800x400/0A1628/FFFFFF?text=医药健康+AI岗位洞察平台)

## 🌟 功能特性

### 📊 数据可视化
- **平台生态概览** - 三大招聘平台数据对比
- **薪资分布洞察** - 行业薪资水平与分布分析
- **地域机会分布** - 各城市岗位数量与薪资对比
- **核心技能图谱** - 热门技能需求排行
- **经验要求分析** - 不同经验段的岗位分布

### 🔍 智能筛选与排序
- **多维度筛选** - 工作年限、学历、岗位等级、城市、平台
- **关键词搜索** - 岗位名称、技能、概述搜索
- **智能排序** - 发布时间、薪资、公司体量、岗位等级
- **自动去重** - 同一公司相同岗位只保留最新发布

### 🔄 每日自动更新
- 实时同步三大平台数据
- 自动识别新增、更新、下线岗位
- 今日更新统计展示

### 👔 猎头资源
- **专业猎头顾问** - 点击头像进入招聘网站主页
- **知名猎头机构** - 点击机构访问官网
- 覆盖医药健康+AI领域专业猎头

## 🛠 技术栈

- **前端框架**: React 18 + TypeScript
- **构建工具**: Vite 5
- **样式方案**: Tailwind CSS 3.4
- **UI组件**: shadcn/ui
- **数据可视化**: Recharts
- **动画效果**: Framer Motion
- **图标库**: Lucide React

## 📁 项目结构

```
my-app/
├── public/
│   └── data/
│       ├── jobs.json           # 岗位数据
│       ├── stats.json          # 统计数据
│       ├── headhunters.json    # 猎头数据
│       └── agencies.json       # 猎头机构数据
├── src/
│   ├── App.tsx                 # 主应用组件
│   ├── App.css                 # 全局样式
│   ├── index.css               # 入口样式
│   └── main.tsx                # 入口文件
├── index.html
├── package.json
├── tsconfig.json
├── tailwind.config.js
└── vite.config.ts
```

## 🚀 快速开始

### 环境要求
- Node.js >= 18.0.0
- npm >= 9.0.0

### 安装依赖

```bash
npm install
```

### 开发模式

```bash
npm run dev
```

### 生产构建

```bash
npm run build
```

### 预览生产构建

```bash
npm run preview
```

## 📊 数据结构

### 岗位数据 (Job)

```typescript
interface Job {
  id: number
  platform: string           // 招聘平台
  title: string              // 岗位名称
  company: string            // 公司名称
  company_scale_value: number // 公司体量评分
  company_scale: string      // 公司规模
  company_level: string      // 公司级别
  city: string               // 城市
  salary_min: number         // 最低薪资(K)
  salary_max: number         // 最高薪资(K)
  experience: string         // 工作经验
  education: string          // 学历要求
  job_level: string          // 岗位等级
  summary: string            // 岗位概述
  skills: string[]           // 技能要求
  publish_date: string       // 发布日期
  update_date: string        // 更新日期
  status: 'active' | 'deleted' | 'updated'
}
```

### 猎头数据 (Headhunter)

```typescript
interface Headhunter {
  id: number
  name: string               // 猎头姓名
  avatar: string             // 头像URL
  company: string            // 所属公司
  company_url: string        // 公司URL
  profile_url: string        // 个人主页URL
  platform: string           // 所在平台
  specialty: string          // 专业领域
  experience: string         // 从业经验
}
```

### 猎头机构数据 (Agency)

```typescript
interface Agency {
  id: number
  name: string               // 机构名称
  logo: string               // Logo URL
  website: string            // 官网URL
  description: string        // 机构描述
  platforms: string[]        // 覆盖平台
}
```

## 🎨 设计特色

- **深色科技风** - 深蓝底色搭配科技蓝渐变
- **流畅动画** - Framer Motion实现滚动触发动画
- **玻璃拟态** - 半透明卡片与模糊背景效果
- **响应式设计** - 完美适配桌面与移动设备

## 📝 更新日志

### v1.1.0 (2024-02-19)
- ✨ 新增猎头资源板块
- ✨ 新增薪资区间分布详情Tooltip
- ✨ 新增每日更新按钮交互
- 🔧 将"公司实力"改为"公司体量"

### v1.0.0 (2024-02-19)
- 🎉 项目初始发布
- ✨ 岗位数据可视化
- ✨ 智能筛选与排序
- ✨ 每日自动更新

## 📄 许可证

MIT License © 2024 医药健康AI人才洞察平台

## 🤝 贡献

欢迎提交Issue和Pull Request！

---

> 💡 **提示**: 本项目数据仅供演示使用，实际使用时请替换为真实数据源。
