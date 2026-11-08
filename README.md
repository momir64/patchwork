# Patchwork

A desktop app that collects the shows, movies and albums you watch and listen to, and turns them into poster collages.

![Patchwork library](docs/screenshots/library.png)

## Overview

Patchwork pulls your libraries from the services where they already live, lets you organize and clean them up, and
renders the result as a poster collage. Everything is stored locally as plain JSON and image files.

It is written in Python with PySide6 (Qt) and also ships with a command-line interface.

## Features

- **Syncing.** Sonarr and Radarr for what you own, Trakt for what you have watched and rated, Last.fm and Spotify data
  exports for what you listen to. Posters and details come from those sources, with TMDB, MusicBrainz, Deezer and
  iTunes as fallbacks.
- **Browsing.** Shows, movies and albums each get their own library. Search, filter by genre, country, language or
  group, and sort by year, rating, date added or cover color.
- **Organizing.** Favorites, custom groups (drag to reorder), renaming, hiding, and a duplicate finder that catches
  editions of the same item by name, shared IDs and visually similar covers.
- **Collages.** Build from favorites, a group, a selection or everything. Justified rows or a fixed grid, any aspect
  ratio, ordered A-Z, shuffled or by color. The live preview re-renders at full detail as you zoom in.

![Filters and selection](docs/screenshots/filters.png)

## Collages

| Shows | Albums |
| --- | --- |
| ![Shows collage](docs/collages/shows.jpg) | ![Albums collage, sorted by color](docs/collages/albums.jpg) |

![Albums collage, sorted by color](docs/collages/color.jpg)

## Setup

Requires Python 3.10 or newer.

```
pip install -r requirements.txt
python main.py        # or run.bat on Windows
```

Open **Settings** and enter the details for the services you use. None of them is required, and each has a *Test
connection* button. The same values can be placed in a `.env` file (see `.env.example`).

| Service | What you need |
| --- | --- |
| Sonarr / Radarr | address and API key |
| Trakt | a Client ID from your own Trakt app, and your public username |
| Last.fm | an API key and your username |
| TMDB | an API key, used for missing posters and details |
| Spotify | no key; import the data export you can request from your account |

Press **Sync** in the sidebar. The first run is slow, mostly because album genres and countries come from MusicBrainz
at about one artist per second. Later syncs only fetch what is new.

## Usage

1. **Sync** to fill the libraries.
2. **Browse** the pages, star favorites and add items to groups. Right-click for rename, hide and remove.
3. **Clean up** with the *Duplicates* button on each page.
4. Open **Collage**, choose a shape, size and order, then press *Generate collage*. The image is written to
   `data/output`.

![Collage page](docs/screenshots/collage.png)

Some defaults to be aware of: syncing only adds items and never removes them; Radarr only adds movies that are
unmonitored (configurable in Settings); and Trakt never changes your favorites unless you enable it.

## Building a standalone executable

`build.bat` packages the app with PyInstaller (it installs PyInstaller and the requirements first). The build is
described in `patchwork.spec` and produces two single-file executables:

```
build.bat
```

| File | Purpose |
| --- | --- |
| `dist\patchwork.exe` | the GUI, opens without a console window |
| `dist\patchwork-cli.exe` | the command-line interface (see below), a smaller console build without Qt |

Both keep their `.env` and `data/` folder next to themselves, so they can be moved around together or run from a USB
stick. When packaged, use `patchwork-cli.exe` in place of `python main.py` in the commands below.

## Command line

Syncing and collages also work without the GUI:

```
python main.py sync [sonarr|radarr|trakt|lastfm]
python main.py collage shows --favs --aspect 2:3 --width 4000
python main.py collage albums --order hue --direction diagonal
python main.py export backup.zip
python main.py --help
```

## Data

Everything lives in `data/` next to the app: one folder per media type containing `library.json`, `meta.json`,
`groups.json` and a `posters/` folder, plus `output/` for generated collages. **Settings -> Your data** exports all of
it to a single file (API keys excluded) and imports it back.

## Project layout

```
src/core       library, metadata, groups, duplicates, storage
src/sources    one module per service, plus sync.py
src/collage    layout (row balancing) and rendering
src/gui        the Qt app
```

The poster grid is a custom-painted list view rather than thousands of widgets, which keeps the interface responsive
with libraries of tens of thousands of items. Most of that lives in `src/gui/media_page.py`.

## Troubleshooting

If the application crashes, a traceback is written to `data/crash.log`. Suggestions and bug reports are welcome.

## License

[TWAORPWB](LICENSE): thou wilt at own risk, praise with beer.
