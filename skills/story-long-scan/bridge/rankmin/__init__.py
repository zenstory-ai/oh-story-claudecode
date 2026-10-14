"""Qidian, Fanqie, Ciweimao, and JJWXC rank providers. Dispatch is rankmin.providers."""

from .ciweimao import fetch_ciweimao_rank
from .fanqie import fetch_fanqie_rank
from .jjwxc import fetch_jjwxc_rank
from .qidian import fetch_qidian_mobile

__all__ = [
    "fetch_ciweimao_rank",
    "fetch_fanqie_rank",
    "fetch_jjwxc_rank",
    "fetch_qidian_mobile",
]
