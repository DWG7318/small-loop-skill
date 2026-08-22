---
name: slk-grill-supervisor
description: Use when a newly assigned SLK Supervisor needs to demonstrate practical understanding before engineering begins.
---

# Grill the SLK Supervisor

## 当前目标

确认 Supervisor 能用自己的话解释 SLK，并能把方法应用到当前 Run。这里检验理解，不追求固定题数或背诵原文。

## 问答方式

- 一次只问一个问题，根据回答继续追问。
- 问题数量随理解程度变化；清楚的回答可以快速通过，模糊回答值得继续澄清。
- 回答偏离时，先解释容易混淆的地方，再换一种问法确认。
- 问题结合当前 Run，让 Supervisor 说明自己准备怎样做。

## 建议覆盖

1. SLK 的适用范围，以及一个 Run、线性 GO、线性 CELL 的含义。
2. Supervisor、Checker、Worker 的职责和创建关系。
3. D0、D1、D2分别解决什么问题，以及检查如何减少重复。
4. CELL 大小怎样参考模型、电脑、累积工程量和余量。
5. Worker 与 Checker 的隔离、通讯和返工关系。
6. 通讯异常、成员异常、连续返工和 D2 发现组合问题时如何恢复施工。
7. 根 Run 记录由谁创建，各成员怎样记录和传输。
8. Supervisor 怎样保持 Run 连续推进。面对允许误差或豁免时，可以说明影响与剩余问题、写入根记录、安排补偿或后续 CELL，并明确下一责任人与下一步；豁免不等于 D1 通过，两者分别保留。
9. 什么情况下值得联系 Owner，什么情况可以由 Supervisor 组织成员继续处理。

## 完成后

当 Supervisor 能稳定解释这些关系并给出当前 Run 的可行处理方式时，建议进入 `$slk-manage-team` 建立 Checker 与 Worker。
