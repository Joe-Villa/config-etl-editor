"""Display palettes: category label -> RGB. Data labels live in province_model."""

from __future__ import annotations

# 未着色 / 无数据 / 海域 — 所有图层统一为白色
UNCOLORED_RGB = (255, 255, 255)

TERRAIN_PALETTE: dict[str, tuple[int, int, int]] = {
    "sea": UNCOLORED_RGB,
    "normal": (140, 175, 110),
    "prime": (255, 200, 50),
    "impassable": (200, 60, 60),
}

HUB_PALETTE: dict[str, tuple[int, int, int]] = {
    "sea": UNCOLORED_RGB,
    "normal": (140, 175, 110),
    "city": (200, 60, 200),
    "port": (60, 120, 220),
    "farm": (120, 190, 80),
    "mine": (150, 100, 60),
    "wood": (40, 120, 50),
}

INCORPORATION_PALETTE: dict[str, tuple[int, int, int]] = {
    "sea": UNCOLORED_RGB,
    "unowned": UNCOLORED_RGB,
    "incorporated": (70, 130, 200),
    "unincorporated": (220, 140, 50),
}

HOMELAND_NONE_RGB = (200, 200, 208)
HOMELAND_MULTI_RGB = (150, 90, 200)

SLAVERY_NO_SLAVES_RGB = (210, 220, 210)
SLAVERY_MIN_RGB = (255, 210, 230)
SLAVERY_MAX_RGB = (130, 45, 95)

POP_TOTAL_ZERO_RGB = (245, 245, 250)
POP_TOTAL_MAX_RGB = (35, 55, 130)

# 宣称数量：固定绝对刻度（与全局最大值无关），0 = 与海域同色
CLAIM_COUNT_SCALE = 8
CLAIM_MIN_RGB = (255, 185, 175)  # 1 宣称：浅珊瑚红
CLAIM_MAX_RGB = (190, 28, 48)  # 8+ 宣称：深绯红

HUB_TYPE_ZH = {
    "city": "城市",
    "port": "港口",
    "farm": "农业区",
    "mine": "矿区",
    "wood": "林业区",
}

VANILLA_COUNTRY_TYPES: frozenset[str] = frozenset(
    {"recognized", "colonial", "unrecognized", "decentralized", "company"}
)

COUNTRY_TYPE_PALETTE: dict[str, tuple[int, int, int]] = {
    "sea": UNCOLORED_RGB,
    "unowned": UNCOLORED_RGB,
    # 受认可：国际体系内的正统主权，用外交/官方感的钴蓝
    "recognized": (55, 115, 195),
    # 殖民：帝国海外直辖/附属，赭橙土色（与商业金、部落绿区分）
    "colonial": (185, 95, 55),
    # 未受认可：游离于承认体系外，暗红/锈红表 contested legitimacy
    "unrecognized": (170, 65, 75),
    # 松散部族：可殖民 frontier，橄榄绿表非集权/自然政体
    "decentralized": (88, 138, 78),
    # 公司：特许商业实体，金色表财富与贸易
    "company": (220, 180, 45),
    # 模组自定义类型：高饱和品红，与以上五色均易区分
    "custom": (190, 70, 190),
}
