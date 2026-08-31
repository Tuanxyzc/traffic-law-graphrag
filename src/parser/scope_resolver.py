"""
scope_resolver.py — Filter VanBan based on SCOPE_CONFIG.
"""

from copy import deepcopy

from src.config import SCOPE_CONFIG
from src.parser.models import Chuong, VanBan


def apply(van_ban_full: VanBan) -> VanBan:
    """
    Returns a new VanBan object containing only the Articles (Điều)
    that are IN_SCOPE according to SCOPE_CONFIG.
    """
    cfg = SCOPE_CONFIG.get(
        van_ban_full.so_hieu, SCOPE_CONFIG.get("default", {"scope_mode": "ALL"})
    )
    mode = cfg.get("scope_mode", "ALL")

    if mode == "ALL":
        return deepcopy(van_ban_full)

    selected = set(cfg.get("selected_articles", []))

    vb_selected = VanBan(
        so_hieu=van_ban_full.so_hieu,
        ten=van_ban_full.ten,
        loai=van_ban_full.loai,
        chuong=[],
        dieu_khong_chuong=[],
    )

    # Filter dieu_khong_chuong
    for d in van_ban_full.dieu_khong_chuong:
        if d.so in selected:
            vb_selected.dieu_khong_chuong.append(deepcopy(d))

    # Filter chuong
    for c in van_ban_full.chuong:
        c_new = Chuong(id=c.id, so=c.so, tieu_de=c.tieu_de, dieu=[])
        for d in c.dieu:
            if d.so in selected:
                c_new.dieu.append(deepcopy(d))
        if c_new.dieu:
            vb_selected.chuong.append(c_new)

    return vb_selected
