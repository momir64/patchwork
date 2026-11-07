# Patchwork

Patchwork is a desktop app that turns the shows, movies and albums you've consumed into balanced poster and album-cover
collages. It syncs your library from Sonarr, Radarr, Trakt and Last.fm, stores lists, favorites and metadata as plain
text and JSON, and lets you build collages from favorites or custom groups like "Sci-fi" or "Metal", in any aspect ratio.

    pip install -r requirements.txt
    run.bat                      # or: python main.py

## Connect your services
**Settings** in the app (or `.env`): Sonarr, Radarr, Trakt (Client ID + public username), Last.fm, TMDB. Each has a *Test connection* button.

- **Trakt favorites**: off by default. Turn on *Let Trakt sync change my favorites* to mark titles you rated at or above a
  threshold as favorites. With it off, syncing never touches your favorites.
- **Albums to import** (`LASTFM_LIMIT`): how many of your most played albums (ranked by play count) to import from Last.fm.
  Default 1024, no upper limit, `0` imports all of them.

## Sync - choose exactly what to update
- **Sync** button (bottom of the sidebar) runs your last choice; the sliders button next to it opens the options.
- Pick **sources** (Sonarr, Radarr, Trakt shows / movies, Last.fm), **steps** (new titles, missing posters, missing metadata,
  optionally re-fetch metadata) and which **media types** get posters / metadata.
- Album genres and countries come from MusicBrainz (about one artist per second, so the first run takes a while); Last.fm tags
  are the fallback. Serbian, Croatian and Bosnian are treated as one language (Serbo-Croatian).
- Nothing is ever deleted by a sync. CLI: `python main.py sync sonarr --only posters --kinds shows`.

## Using it
- **Shows / Movies / Albums**: click posters to select (shift-click = range, *Select all* toggles to *Unselect all*), click the
  star for favorites, filter by genre / country / language / group, right-click for rename / replace poster / groups.
  Favoriting or unfavoriting several titles at once asks for confirmation. Renames are remembered in `data/aliases.txt`
  so syncs don't re-add the old name. Posters grow to fill the window width.
- **Groups** live under their category in the sidebar, like subfolders. A group belongs to exactly one category. Create one
  with the **+** next to a category, or with *Add to group* on selected titles. Right-click a group to make a collage, rename or delete it.
- **Collage** (button above Sync): opens with what you were just looking at (selection, otherwise everything shown) as
  *Current view*; or choose all items, favorites or a group of the chosen media type. Order (A-Z, Z-A, shuffle, or by color / lightness running vertically, horizontally or diagonally), justified rows or even grid,
  aspect ratio (2:3, 3:4, 4:5, 1:1, 16:9, with Portrait/Landscape switch), size, gap, color. The preview always shows the whole
  collage; *Generate* writes the full image to `data/output`. Rows are balanced automatically, so the last row is never stretched.
- The window resizes down to 720 px wide (the sidebar collapses to icons) and opens on the monitor your mouse is on.

## Export / import
**Settings > Your data**: export everything media related (lists, favorites, metadata, groups, name fixes) to one file.
`.zip` includes the posters, `.json` is data only. Import merges into what you have and never deletes. Secrets are not exported.
CLI: `python main.py export backup.zip`, `python main.py import backup.zip`.

## Terminal
    python main.py sync [sonarr|radarr|trakt|lastfm] [--only titles posters metadata] [--kinds shows movies albums]
    python main.py list shows --favs
    python main.py collage shows --favs --aspect 2:3 --width 4000 [--landscape] [--grid] [--order hue --direction diagonal]
    python main.py import-legacy <old series_collage folder>

## Where things live
    src/core       config, lists, metadata, groups
    src/sources    one module per service (arr, trakt, tmdb, lastfm, musicbrainz) + sync.py
    src/collage    layout.py (balancing maths) and render.py (images)
    src/gui        app, sidebar, media_page (libraries + groups), collage_page, dialogs, widgets, icons, theme
    tools/         make_icon.py (regenerates assets/icon.png + icon.ico)
    data/<shows|movies|albums>/   list.txt  favorites.txt  meta.json  posters/  groups/<name>.txt
    data/aliases.txt  data/ui.json  data/output/
