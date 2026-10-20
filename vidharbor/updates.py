"""Check GitHub Releases for a newer VidHarbor build."""
from __future__ import annotations

import json

from . import GITHUB_REPO, __version__
from .engine import _fetch, _vtuple


def latest_release(proxy: str = '') -> dict | None:
    """Return {'version', 'page', 'installer'} for the newest release if it is
    newer than this build, else None. Raises on network errors."""
    if not GITHUB_REPO or GITHUB_REPO.startswith('OWNER/'):
        return None
    data = json.loads(_fetch(f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest', proxy=proxy))
    tag = (data.get('tag_name') or '').lstrip('vV')
    if not tag or _vtuple(tag) <= _vtuple(__version__):
        return None
    installer = next((a['browser_download_url'] for a in data.get('assets', [])
                      if a['name'].lower().endswith('setup.exe')), None)
    return {'version': tag, 'page': data.get('html_url'), 'installer': installer or data.get('html_url')}
