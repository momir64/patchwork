"""Terminal interface:  python main.py <command>   (no command = open the GUI)"""
import argparse
import sys
from pathlib import Path

from .collage import render
from .core.config import Config
from .core.library import KINDS, Library


def build_parser():
    p = argparse.ArgumentParser(prog="patchwork", description="Collages of the media you consumed.")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("sync", help="update lists/posters from Sonarr, Radarr, Trakt, Last.fm")
    s.add_argument("sources", nargs="*", choices=["sonarr", "radarr", "trakt", "lastfm", "spotify"], help="default: all configured")
    s.add_argument("--only", nargs="+", choices=["titles", "posters", "metadata"], help="run just these steps")
    s.add_argument("--kinds", nargs="+", choices=list(KINDS), help="limit posters/metadata to these media types")
    s.add_argument("--refresh-metadata", action="store_true", help="re-fetch metadata even where it exists")
    l = sub.add_parser("list", help="print a list")
    l.add_argument("kind", choices=KINDS)
    l.add_argument("--favs", action="store_true")
    c = sub.add_parser("collage", help="build a collage")
    c.add_argument("kind", choices=["shows", "movies", "albums", "images", "videos"], help="'videos' = shows + movies")
    c.add_argument("--favs", action="store_true", help="only favorites")
    c.add_argument("--width", type=int, default=4000)
    c.add_argument("--row-height", type=int, default=300)
    c.add_argument("--gap", type=int, default=0)
    c.add_argument("--grid", action="store_true", help="fixed grid instead of justified rows")
    c.add_argument("--columns", type=int, default=0)
    c.add_argument("--order", choices=["az", "za", "shuffle", "hue", "bright"], default="az")
    c.add_argument("--direction", choices=["vertical", "horizontal", "diagonal"], default="vertical", help="for --order hue/bright")
    c.add_argument("--color-mode", choices=["average", "dominant", "accent"], default="average", help="for --order hue: how an image's color is judged")
    c.add_argument("--reverse", action="store_true", help="reverse a hue / bright order")
    c.add_argument("--crop", action="store_true", help="fill every cell (crops) instead of only resizing images")
    c.add_argument("--aspect", default="", help="overall shape W:H, e.g. 2:3 portrait, 1:1 square, 16:9 wide")
    c.add_argument("--landscape", action="store_true", help="flip --aspect to landscape (default is portrait)")
    c.add_argument("--png", action="store_true")
    e = sub.add_parser("export", help="export all media data to one file (.zip with posters, or .json data only)")
    e.add_argument("path", type=Path)
    e.add_argument("--settings", action="store_true", help="also include the settings (.env), API keys included")
    m = sub.add_parser("import", help="merge an export file into the current data")
    m.add_argument("path", type=Path)
    m.add_argument("--overwrite-posters", action="store_true")
    m.add_argument("--settings", action="store_true", help="also import the settings (.env) when the file has them")
    sp = sub.add_parser("import-spotify", help="import albums from Spotify export files (YourLibrary.json, Playlist*.json)")
    sp.add_argument("files", nargs="+", type=Path)
    sp.add_argument("--min-tracks", type=int, default=3, help="songs an album needs in liked songs / playlists (saved albums always count)")
    sp.add_argument("--no-liked", action="store_true")
    sp.add_argument("--no-playlists", action="store_true")
    sp.add_argument("--no-posters", action="store_true", help="skip downloading covers")
    sp.add_argument("--metadata", action="store_true", help="also fetch genres / country (about 1 artist per second)")
    sub.add_parser("spotify-login", help="sign in to Spotify in the browser, so that sync can read your account")
    i = sub.add_parser("import-legacy", help="import the old series_collage folder")
    i.add_argument("path", type=Path)
    return p


def collect(kinds, favs):
    out = []
    for k in kinds:
        lib = Library(k)
        out += [(lib.poster(i), i) for i in (lib.favorites() if favs else lib.items) if lib.poster(i) and render.readable(lib.poster(i))]
    return out


def run(argv):
    a = build_parser().parse_args(argv)
    if a.cmd == "sync":
        from .sources import Sync
        from .sources.sync import STEPS
        cfg = Config()
        libs = {k: Library(k) for k in KINDS}
        names = a.sources or ["sonarr", "radarr", "trakt", "lastfm", "spotify"]
        sources = [x for n in names for x in (("trakt_shows", "trakt_movies") if n == "trakt" else (n,))]
        res = Sync(cfg, libs, log=print).run(sources, tuple(a.only or STEPS), tuple(a.kinds or KINDS), a.refresh_metadata)
        print("Done:", ", ".join(res) or "nothing to do")
    elif a.cmd == "list":
        lib = Library(a.kind)
        print("\n".join(lib.favorites() if a.favs else lib.items))
    elif a.cmd == "collage":
        kinds = ["shows", "movies"] if a.kind == "videos" else [a.kind]
        pairs = collect(kinds, a.favs)
        if not pairs:
            sys.exit("No items with posters found.")
        by_label = {l: p for p, l in pairs}
        order = render.order_items(list(by_label), a.order, 1, by_label, a.color_mode, a.reverse)
        paths = [by_label[l] for l in order]
        o = render.Options(mode="grid" if a.grid else "justified", width=a.width, gap=a.gap, row_height=a.row_height,
                           columns=a.columns, aspect=render.aspect_from(a.aspect, a.landscape), order=a.order, direction=a.direction, color_mode=a.color_mode, reverse=a.reverse, fit="crop" if a.crop else "keep", fmt="PNG" if a.png else "JPEG")
        lay = render.make_layout(paths, o)
        if a.order in ("hue", "bright"):
            paths = render.arrange(paths, lay, a.direction)
        print(f"{len(paths)} images -> {lay.width}x{lay.height}, {lay.rows} rows, row-height spread {lay.spread:.1%}")
        out = render.save(render.render(paths, lay, o.bg, lambda n, t: print(f"\r{n}/{t}", end="", flush=True)),
                          f"{a.kind}{'_favs' if a.favs else ''}", o)
        print("\nSaved", out)
    elif a.cmd == "export":
        from .core.transfer import export_data
        export_data(a.path, settings=a.settings)
    elif a.cmd == "import":
        from .core.transfer import import_data
        import_data(a.path, a.overwrite_posters, settings=a.settings)
    elif a.cmd == "import-spotify":
        from .sources import Sync
        libs = {k: Library(k) for k in KINDS}
        Sync(Config(), libs, log=print).import_spotify(a.files, not a.no_liked, not a.no_playlists, a.min_tracks,
                                                       not a.no_posters, a.metadata)
    elif a.cmd == "spotify-login":
        from .sources import spotify_user
        print("Opening Spotify in the browser. Redirect address of your app:", spotify_user.redirect(Config()))
        print("Signed in as", spotify_user.sign_in(Config()))
    elif a.cmd == "import-legacy":
        from .importer import import_legacy
        import_legacy(a.path)
    else:
        from .gui.app import main
        main()
