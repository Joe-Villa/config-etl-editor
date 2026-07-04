"""PM 组初始选中项：游戏脚本中列出的第一个生产方式。

注意：default_building_* / pm_default_* 是 PM 名称（如种植园「基础生产」），
不是「默认选中」的语义；选中第一项即可。
"""


def first_pm_for_group(pms: list[str]) -> str | None:
    if not pms:
        return None
    return pms[0]
