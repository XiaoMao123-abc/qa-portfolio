# QA Portfolio｜测试工程师作品集

软件测试方向的练习与项目仓库。所有内容均基于真实可运行的代码与工具实践，不写空话。

## 技能栈

**编程语言**：Python

**测试类型**：接口测试、接口自动化测试、功能测试、性能测试

**工具**：pytest、requests、Postman、JMeter、Fiddler、Allure、Jenkins、Git

**基础**：MySQL、Linux、TCP/IP、adb

## 目录结构

```
qa-portfolio/
├── scripts/                 # 日常测试小工具脚本
│   └── log_analyzer.py      # 日志分析工具：级别统计、错误堆栈提取、时间聚合
└── api-test-framework/      # 接口自动化框架（规划中）
    ├── api/                 # 接口封装层
    ├── cases/               # 测试用例层
    ├── data/                # 测试数据层
    ├── config/              # 配置层
    ├── utils/               # 工具层
    └── report/              # Allure 报告输出
```

## 项目

### 1. log_analyzer —— 日志分析工具

命令行工具，用于快速定位测试环境的异常日志。

解决的问题：线上/测试环境出问题时需要从大量日志中找出错误分布与堆栈上下文，纯手工翻日志效率低。

```bash
# 统计日志级别分布
python scripts/log_analyzer.py app.log --stats

# 提取 ERROR 及其后 5 行堆栈上下文
python scripts/log_analyzer.py app.log --level ERROR --context 5

# 按小时聚合错误数量，定位问题集中时段
python scripts/log_analyzer.py app.log --hourly

# 关键字检索
python scripts/log_analyzer.py app.log --grep "timeout"
```

### 2. api-test-framework —— 接口自动化框架（进行中）

基于 pytest + requests 的数据驱动接口自动化框架，分层设计（api / cases / data / config / utils / report），计划接入 Jenkins 实现每日定时巡检与报告推送。

## 环境

- Python 3.14
- Windows / Linux
