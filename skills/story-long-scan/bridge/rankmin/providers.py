"""One provider per rank site. The CLI dispatches through this table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .contracts import RankSnapshot

FetchRank = Callable[..., RankSnapshot]


@dataclass(frozen=True)
class RankProvider:
    site_id: str
    transport: str
    defaults: tuple[str, ...]
    fetch: FetchRank


def provider_map() -> dict[str, RankProvider]:
    from .ciweimao import DEFAULT_CATEGORIES as ciweimao_defaults
    from .ciweimao import fetch_ciweimao_rank
    from .fanqie import DEFAULT_CATEGORIES as fanqie_defaults
    from .fanqie import fetch_fanqie_rank
    from .jjwxc import DEFAULT_CATEGORIES as jjwxc_defaults
    from .jjwxc import fetch_jjwxc_rank
    from .qidian import DEFAULT_CATEGORIES as qidian_defaults
    from .qidian import fetch_qidian_mobile

    ordered = (
        RankProvider("qidian", "urllib", qidian_defaults, fetch_qidian_mobile),
        RankProvider("fanqie", "curl_cffi", fanqie_defaults, fetch_fanqie_rank),
        RankProvider("ciweimao", "curl_cffi", ciweimao_defaults, fetch_ciweimao_rank),
        RankProvider("jjwxc", "urllib", jjwxc_defaults, fetch_jjwxc_rank),
    )
    return {provider.site_id: provider for provider in ordered}
