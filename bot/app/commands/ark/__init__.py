from .search import register_search
from .render import register_render
from .colors import register_colors
from .reaper import register_reaper
from .help import register_help


def register_ark_commands(ark_group, cache) -> None:
    register_search(ark_group, cache)
    register_render(ark_group, cache)
    register_colors(ark_group, cache)
    register_reaper(ark_group)
    register_help(ark_group, cache)
