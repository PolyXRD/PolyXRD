"""外部精修程序启动器 (v0.15 M25-3/M25-4)

- :mod:`gsas2_launcher` — GSAS-II GUI 拉起 (数据/CIF 导出 + Popen)
- :mod:`maud_launcher`  — MAUD GUI 拉起 (xye/CIF 导出 + Popen)

降级语义 (路线图 M25 风险登记): 能回读的回读, 不能回读的只做
「导出 + 拉起」— 两个启动器都先在 workdir 落盘实验数据与物相 CIF,
再拉起外部 GUI, 由用户在 GUI 内继续操作。
"""
