import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import wraps
from operator import attrgetter, itemgetter
from pathlib import Path

import dinghy.digest
from aiohttp import web
from chameleon import PageTemplateLoader
from dinghy.helpers import parse_timedelta
from dinghy.jinja_helpers import render_jinja


routes = web.RouteTableDef()


class _ProjectDigestStore:
    def __init__(self, repo, max_look_back, refresh_after=timedelta(minutes=30)):
        self._repo = repo
        self._max_look_back = max_look_back
        self._refresh_after = refresh_after
        self._last_entry = datetime.today() - 2 * max_look_back
        self._lock = asyncio.Lock()
        self._digest = {}
        self._entries = []

    async def get(self, since):
        async with self._lock:
            if self._last_entry < utctoday() - self._max_look_back:
                await self._refresh(utctoday() - self._max_look_back)
            elif datetime.utcnow() > self._last_entry + self._refresh_after:
                await self._refresh(self._last_entry)

            to_datetime = lambda value: datetime.fromisoformat(
                value.replace("Z", "+00:00")
            ).replace(tzinfo=None)
            entries = [
                entry
                for entry in self._entries
                if to_datetime(entry["updatedAt"]) > since
            ]
            return dict(self._digest, entries=entries)

    async def _refresh(self, since):
        self._last_entry = datetime.utcnow()
        digester = dinghy.digest.Digester(since=since, options={})
        digester.prepare()
        result = await dinghy.digest.coro_from_item(digester, self._repo)
        self._digest = {k: v for (k, v) in result.items() if k != "entries"}
        if entries := result["entries"]:
            self._entries = self._merge_entries(self._entries, entries)

    @staticmethod
    def _merge_entries(existing, new):
        result = {entry["id"]: entry for entry in existing}
        for entry in new:
            result[entry["id"]] = entry
        return sorted(result.values(), key=itemgetter("updatedAt"))


class DigestStore:
    def __init__(self, max_look_back=timedelta(days=7)):
        self._max_look_back = max_look_back
        self._stores = {}

    async def get(self, project, since):
        if project.name not in self._stores:
            self._stores[project.name] = _ProjectDigestStore(
                project.repo, self._max_look_back
            )
        store = self._stores[project.name]
        return await store.get(since)


@dataclass
class Project:
    name: str
    repo: str

    def url(self, request, since: str):
        return request.app.router["digest"].url_for(project=self.name, since=since)


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


@routes.get("/")
@render("index.html")
def handle_root(request):
    return {
        "projects": sorted(request.app["projects"].values(), key=attrgetter("name")),
    }


@routes.get("/{project}/{since}", name="digest")
async def handle_project(request):
    project = request.app["projects"].get(request.match_info["project"])
    if project is None:
        raise web.HTTPNotFound()
    since = utctoday() - parse_timedelta(request.match_info["since"])
    digest = await request.app["digest_store"].get(project, since)
    page = render_jinja(
        "digest.html.j2",
        results=[digest],
        since=since,
        now=datetime.now(),
        __version__=dinghy.__version__,
    )
    return web.Response(text=page, content_type="text/html")


def _parse_projects(urls):
    projects = {}
    for url in urls:
        name = url.rsplit("/", 1)[-1]
        if "://" not in url:
            url = "https://github.com/" + url
        projects[name] = Project(name=name, repo=url)
    return projects


def main():
    if "GITHUB_TOKEN_FILE" in os.environ:
        with open(os.environ["GITHUB_TOKEN_FILE"]) as token_file:
            os.environ["GITHUB_TOKEN"] = token_file.read().strip()
    if "GITHUB_TOKEN" not in os.environ:
        print("[FATAL] Environment variable GITHUB_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    app = web.Application()
    app["projects"] = _parse_projects(
        os.environ.get("PROJECTS", "").split() + sys.argv[1:]
    )
    app["digest_store"] = DigestStore()
    app["template_loader"] = PageTemplateLoader(
        str(Path(__file__).parent / "templates")
    )
    app.add_routes(routes)

    port = int(os.environ.get("PORT", "8080"))
    web.run_app(app, port=port)


if __name__ == "__main__":
    main()
