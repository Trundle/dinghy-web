import asyncio
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps
from itertools import chain
from operator import itemgetter
from pathlib import Path
from typing import Any

import dinghy.digest
import yaml
from aiohttp import web
from chameleon import PageTemplateLoader
from dinghy.graphql_helpers import GraphqlHelper
from dinghy.helpers import parse_timedelta
from dinghy.jinja_helpers import render_jinja


_BACK_LINKS_PLACES = re.compile(r'</h1>|</ul>(?=\s+<p class="footer")')


routes = web.RouteTableDef()


class _DigestItemStore:
    def __init__(self, options, max_look_back, refresh_after=timedelta(minutes=30)):
        options.pop("since", None)
        options.pop("digest", None)
        self._options = options
        self._items = options.pop("items")
        self._max_look_back = max_look_back
        self._refresh_after = refresh_after
        self._last_entry = datetime.today() - 2 * max_look_back
        self._lock = asyncio.Lock()
        self._digests = [{}] * len(self._items)
        self._entries = [[]] * len(self._items)

    async def get(self, since):
        async with self._lock:
            if self._last_entry < utctoday() - self._max_look_back:
                await self._refresh(utctoday() - self._max_look_back)
            elif datetime.utcnow() > self._last_entry + self._refresh_after:
                await self._refresh(self._last_entry)

            to_datetime = lambda value: datetime.fromisoformat(
                value.replace("Z", "+00:00")
            ).replace(tzinfo=None)
            results = []
            for (digest, entries) in zip(self._digests, self._entries):
                entries = [
                    entry
                    for entry in entries
                    if to_datetime(entry["updatedAt"]) > since
                ]
                results.append(dict(digest, entries=entries))
            return results

    async def _refresh(self, since):
        self._last_entry = datetime.utcnow()

        digester = dinghy.digest.Digester(since=since, options=self._options)
        digester.prepare()

        coros = []
        for item in self._items:
            coros.append(dinghy.digest.coro_from_item(digester, item))
        results = await asyncio.gather(*coros)

        for (i, result) in enumerate(results):
            self._digests[i] = {k: v for (k, v) in result.items() if k != "entries"}
            if entries := result["entries"]:
                self._entries[i] = self._merge_entries(self._entries[i], entries)

    @staticmethod
    def _merge_entries(existing, new):
        result = {entry["id"]: entry for entry in existing}
        for entry in new:
            result[entry["id"]] = entry
        return sorted(result.values(), key=itemgetter("updatedAt"), reverse=True)


class ItemStore:
    def __init__(self, max_look_back=timedelta(days=7)):
        self._max_look_back = max_look_back
        self._stores = {}

    async def get(self, digest, since):
        if digest.filename not in self._stores:
            self._stores[digest.filename] = _DigestItemStore(
                digest.options, self._max_look_back
            )
        store = self._stores[digest.filename]
        return await store.get(since)


@dataclass
class Digest:
    title: str
    filename: str
    options: dict[str, Any]

    def url(self, request, since: str):
        return (
            request.app.router["digest"]
            .url_for(filename=self.filename)
            .with_query({"since": since})
        )


def utctoday():
    today = datetime.utcnow().date()
    return datetime(year=today.year, month=today.month, day=today.day)


def render(page_name):
    def decorator(f):
        @wraps(f)
        def render_template(request):
            template_vars = f(request)
            page = request.app["template_loader"][page_name]
            return web.Response(
                text=page.render(request=request, **template_vars),
                content_type="text/html",
            )

        return render_template

    return decorator


@routes.get("/", name="root")
@render("index.html")
def handle_root(request):
    return {
        "digests": request.app["digests"].values(),
        "resource_limit": GraphqlHelper.last_rate_limit(),
    }


@routes.get("/{filename}", name="digest")
async def handle_project(request):
    project = request.app["digests"].get(request.match_info["filename"])
    if project is None:
        raise web.HTTPNotFound()
    since = utctoday() - parse_timedelta(request.query["since"])
    results = await request.app["item_store"].get(project, since)
    page = render_jinja(
        "digest.html.j2",
        results=results,
        since=since,
        now=datetime.now(),
        __version__=dinghy.__version__,
    )
    page = _add_back_links(page, request.app.router["root"].url_for())
    return web.Response(text=page, content_type="text/html")


def _add_back_links(page: str, back_url: str):
    return _BACK_LINKS_PLACES.sub(
        rf'\g<0><a href="{back_url}">← Back to index</a>', page
    )


def _parse_projects(urls):
    for url in urls:
        name = url.rsplit("/", 1)[-1]
        if "://" not in url:
            url = "https://github.com/" + url
        yield Digest(title=name, filename=name + ".html", options={"items": [url]})


def _load_dinghy_config(path):
    with open(path) as config_file:
        config = yaml.safe_load(config_file)

    defaults = config.get("defaults", {})
    for spec in config.get("digests", []):
        filename = spec.get("digest")
        title = spec.get("title") or filename
        yield Digest(title=title, filename=filename, options={**defaults, **spec})


def main():
    if "GITHUB_TOKEN_FILE" in os.environ:
        with open(os.environ["GITHUB_TOKEN_FILE"]) as token_file:
            os.environ["GITHUB_TOKEN"] = token_file.read().strip()
    if "GITHUB_TOKEN" not in os.environ:
        print("[FATAL] Environment variable GITHUB_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) == 2 and Path(sys.argv[1]).exists():
        digests = _load_dinghy_config(sys.argv[1])
    else:
        digests = _parse_projects(sys.argv[1:])
    digests = chain(_parse_projects(os.environ.get("PROJECTS", "").split()), digests)

    app = web.Application()
    app["digests"] = {digest.filename: digest for digest in digests}
    app["item_store"] = ItemStore()
    app["template_loader"] = PageTemplateLoader(
        str(Path(__file__).parent / "templates")
    )
    app.add_routes(routes)

    port = int(os.environ.get("PORT", "8080"))
    web.run_app(app, port=port)


if __name__ == "__main__":
    main()
